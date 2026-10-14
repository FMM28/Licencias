"""Dependencias de FastAPI compartidas por la API JSON y el panel web.

Flujo de cada petición protegida:
  1. optional_ctx   lee la cookie, busca la sesión en BD y comprueba expiración/usuario activo
  2. csrf_check     en métodos que modifican (POST/PUT/PATCH/DELETE): mismo origen + token CSRF
  3. require_perm   exige sesión, que no deba cambiar la contraseña y que el rol tenga el permiso
"""
import secrets
from dataclasses import dataclass
from urllib.parse import urlparse

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core import security
from app.core.config import get_settings
from app.core.errors import (CSRFError, Forbidden, LicenseError, NotAuthenticated,
                             PasswordChangeRequired)
from app.core.ratelimit import client_limiter
from app.db import get_db
from app.models import AdminSession, AdminUser
from app.services import auth as auth_service

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

__all__ = ["AuthContext", "get_db", "client_ip", "limit_client", "cookie_name",
           "set_session_cookie", "clear_session_cookie", "optional_ctx", "require_ctx",
           "require_perm", "same_origin_check", "csrf_check"]


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def limit_client(request: Request) -> None:
    if not client_limiter.allow(client_ip(request), get_settings().rate_limit_per_min):
        raise LicenseError("rate_limited", "Demasiadas solicitudes", 429)


# ------------------------------------------------------------------ sesión
@dataclass
class AuthContext:
    user: AdminUser
    session: AdminSession
    token: str  # token en claro de la cookie (solo vive en memoria durante la petición)

    @property
    def csrf_token(self) -> str:
        return self.session.csrf_token

    @property
    def permissions(self) -> frozenset[str]:
        return security.permissions_for(self.user.role)

    def can(self, permission: str) -> bool:
        return permission in self.permissions


def cookie_name() -> str:
    # El prefijo __Host- obliga al navegador a aceptar la cookie solo si es Secure, sin Domain
    # y con Path=/, lo que impide que un subdominio la pise.
    return "__Host-lic_session" if get_settings().cookie_secure else "lic_session"


def set_session_cookie(response, token: str) -> None:
    response.set_cookie(
        cookie_name(), token, httponly=True, secure=get_settings().cookie_secure,
        samesite="strict", path="/",  # sin max_age: cookie de sesión del navegador
    )


def clear_session_cookie(response) -> None:
    response.delete_cookie(cookie_name(), path="/", httponly=True,
                           secure=get_settings().cookie_secure, samesite="strict")


def optional_ctx(request: Request, db: Session = Depends(get_db)) -> AuthContext | None:
    token = request.cookies.get(cookie_name())
    loaded = auth_service.load_session(db, token)
    if loaded is None:
        return None
    session, user = loaded
    return AuthContext(user=user, session=session, token=token)


def require_ctx(ctx: AuthContext | None = Depends(optional_ctx)) -> AuthContext:
    if ctx is None:
        raise NotAuthenticated()
    return ctx


def require_perm(permission: str | None = None, *, allow_pending_password: bool = False):
    """Fábrica de dependencias: `Depends(require_perm("licenses:write"))`.
    Sin `permission` basta con tener sesión."""
    def dependency(ctx: AuthContext = Depends(require_ctx)) -> AuthContext:
        if ctx.user.must_change_password and not allow_pending_password:
            raise PasswordChangeRequired()
        if permission and not ctx.can(permission):
            raise Forbidden()
        return ctx
    return dependency


# ------------------------------------------------------------------ CSRF
def same_origin_check(request: Request) -> None:
    """Si el navegador envía Origin (siempre lo hace en POST), debe ser este mismo sitio."""
    origin = request.headers.get("origin")
    if origin is None:
        return  # clientes que no son navegadores: los protege el token CSRF
    allowed = {request.headers.get("host"), request.headers.get("x-forwarded-host")}
    allowed.discard(None)
    if origin == "null" or urlparse(origin).netloc not in allowed:
        raise CSRFError()


async def csrf_check(request: Request, ctx: AuthContext | None = Depends(optional_ctx)) -> None:
    if request.method in SAFE_METHODS:
        return
    same_origin_check(request)
    if ctx is None:
        raise NotAuthenticated()
    supplied = request.headers.get("x-csrf-token")
    if not supplied:
        ctype = request.headers.get("content-type", "")
        if ctype.startswith(("application/x-www-form-urlencoded", "multipart/form-data")):
            supplied = (await request.form()).get("csrf_token")
    if not supplied or not secrets.compare_digest(str(supplied), ctx.csrf_token):
        raise CSRFError()
