"""Inicio y cierre de sesión de la API de administración (cookie de sesión + CSRF)."""
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.api.admin._util import invalid_as_422
from app.api.deps import (AuthContext, clear_session_cookie, client_ip, get_db, require_ctx,
                          require_perm, same_origin_check, set_session_cookie)
from app.core import security
from app.core.config import get_settings
from app.core.errors import ApiError, AuthError
from app.core.ratelimit import login_limiter
from app.schemas.admin import LoginIn, MeOut, PasswordChangeIn, UserOut
from app.services import auth as auth_service
from app.services import users as user_service
from app.services.audit import audit

# `public` no exige CSRF (aún no hay sesión); `router` sí (lo añade api/admin/__init__.py).
public = APIRouter(prefix="/auth")
router = APIRouter(prefix="/auth")


def _me(user, csrf_token: str) -> MeOut:
    return MeOut(user=UserOut.model_validate(user, from_attributes=True),
                 permissions=sorted(security.permissions_for(user.role)), csrf_token=csrf_token)


@public.post("/login", response_model=MeOut)
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    same_origin_check(request)
    ip = client_ip(request)
    if not login_limiter.allow(ip, get_settings().login_rate_limit_per_min):
        raise ApiError("rate_limited", "Demasiados intentos. Espera un minuto.", 429)
    try:
        user, token, session = auth_service.authenticate(
            db, body.username, body.password, ip, request.headers.get("user-agent"))
    except AuthError as exc:
        raise ApiError("invalid_credentials", exc.message, 401) from exc
    set_session_cookie(response, token)
    return _me(user, session.csrf_token)


@router.post("/logout")
def logout(request: Request, response: Response, ctx: AuthContext = Depends(require_ctx),
           db: Session = Depends(get_db)):
    auth_service.destroy_session(db, ctx.token)
    audit(db, "admin_logout", ip=client_ip(request), actor=ctx.user.username)
    db.commit()
    clear_session_cookie(response)
    return {"ok": True}


@router.get("/me", response_model=MeOut)
def me(ctx: AuthContext = Depends(require_perm(None, allow_pending_password=True))):
    return _me(ctx.user, ctx.csrf_token)


@router.post("/password")
def change_password(body: PasswordChangeIn,
                    ctx: AuthContext = Depends(require_perm(None, allow_pending_password=True)),
                    db: Session = Depends(get_db)):
    """Cambia tu contraseña y cierra tus demás sesiones (la actual sigue abierta)."""
    with invalid_as_422():
        user_service.change_password(db, ctx.user, body.current, body.new,
                                     keep_session_id=ctx.session.id)
    return {"ok": True}
