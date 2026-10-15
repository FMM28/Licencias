"""Jinja2 (HTML con autoescape), filtros y funciones de render del panel."""
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from fastapi import Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, cookie_name
from app.core import security
from app.core.timeutil import utcnow
from app.db import new_session
from app.services import auth as auth_service
from app.services import licenses as license_service
from app.web import flash

WEB_DIR = Path(__file__).resolve().parent
STATIC_DIR = WEB_DIR / "static"
templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))

STATUS_LABELS = {"active": "Activa", "expiring": "Por vencer", "grace": "En gracia",
                 "expired": "Vencida", "revoked": "Revocada"}
PLAN_LABELS = {"perpetual": "Pago único", "subscription": "Suscripción", "trial": "Prueba"}
EVENT_LABELS = {
    "license_created": "Licencia creada", "activated": "Instalación activada",
    "activate_denied": "Activación rechazada", "activate_failed": "Activación fallida", "validate_denied": "Validación rechazada",
    "deactivated": "Instalación liberada por el cliente", "released": "Activaciones liberadas",
    "revoked": "Licencia revocada", "unrevoked": "Licencia reactivada",
    "extended": "Licencia renovada", "max_activations": "Límite de instalaciones cambiado",
    "notes_updated": "Notas editadas", "ip_changed": "Cambio de IP",
    "admin_login": "Inicio de sesión", "admin_logout": "Cierre de sesión",
    "admin_login_failed": "Inicio de sesión fallido", "admin_login_blocked": "Intento bloqueado",
    "user_created": "Usuario creado", "user_role": "Rol cambiado",
    "user_enabled": "Usuario activado", "user_disabled": "Usuario desactivado",
    "password_reset": "Contraseña restablecida", "password_changed": "Contraseña cambiada",
}
_DANGER = {"activate_denied", "activate_failed", "validate_denied", "revoked", "admin_login_failed",
           "admin_login_blocked", "user_disabled"}
_WARN = {"ip_changed", "released", "deactivated", "password_reset"}
_OK = {"license_created", "activated", "unrevoked", "extended", "admin_login", "user_created",
       "user_enabled"}


def event_tone(event: str) -> str:
    return "danger" if event in _DANGER else "warn" if event in _WARN else \
        "ok" if event in _OK else "neutral"


def asset(path: str) -> str:
    """URL de un archivo estático con parámetro de versión (rompe la caché al recompilar)."""
    try:
        version = int((STATIC_DIR / path).stat().st_mtime)
    except OSError:
        version = 0
    return f"/static/{path}?v={version}"


def _iso(dt: datetime | None) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ") if dt else ""


def _fmt_dt(dt: datetime | None) -> str:
    return dt.strftime("%Y-%m-%d %H:%M UTC") if dt else "—"


def _fmt_date(dt: datetime | None) -> str:
    return dt.strftime("%Y-%m-%d") if dt else "—"


def _rel_days(dt: datetime | None) -> str:
    """Diferencia con hoy, en español: «en 12 días», «hace 3 días», «hoy»."""
    if not dt:
        return ""
    days = (dt.date() - utcnow().date()).days
    if days == 0:
        return "hoy"
    n = abs(days)
    unit = "día" if n == 1 else "días"
    return f"en {n} {unit}" if days > 0 else f"hace {n} {unit}"


def _fp_short(fp: str | None) -> str:
    if not fp:
        return "—"
    return fp if len(fp) <= 16 else f"{fp[:8]}…{fp[-6:]}"


env = templates.env
env.filters.update(iso=_iso, dt=_fmt_dt, date=_fmt_date,
                   status_label=lambda s: STATUS_LABELS.get(s, s),
                   plan_label=lambda p: PLAN_LABELS.get(p, p),
                   role_label=lambda r: security.ROLE_LABELS.get(r, r),
                   event_label=lambda e: EVENT_LABELS.get(e, e),
                   event_tone=event_tone, rel_days=_rel_days, fp_short=_fp_short)
env.globals.update(license_status=license_service.license_status,
                   active_installs=license_service.active_installs, asset=asset, utcnow=utcnow,
                   ROLES=security.ROLES, PLANS=license_service.PLANS,
                   STATUSES=license_service.STATUSES, STATUS_LABELS=STATUS_LABELS,
                   PLAN_LABELS=PLAN_LABELS, ROLE_LABELS=security.ROLE_LABELS,
                   EVENT_LABELS=EVENT_LABELS)


def render(request: Request, name: str, ctx: AuthContext | None = None,
           db: Session | None = None, status_code: int = 200, **context):
    """Renderiza una plantilla con el contexto común (usuario, CSRF, permisos, mensajes)."""
    flashes = []
    if ctx and db and request.method == "GET":
        flashes = flash.pop(db, ctx.session, ctx.token)

    def qs(**overrides) -> str:
        """Query string actual con algunos parámetros cambiados (para paginación y filtros)."""
        params = {**dict(request.query_params), **overrides}
        return urlencode({k: v for k, v in params.items() if v not in (None, "")})

    base = {"user": ctx.user if ctx else None, "csrf_token": ctx.csrf_token if ctx else "",
            "can": ctx.can if ctx else (lambda p: False), "flashes": flashes, "qs": qs,
            "path": request.url.path}
    return templates.TemplateResponse(request, f"pages/{name}", {**base, **context},
                                      status_code=status_code)


def render_error(request: Request, status: int, title: str, message: str):
    """Página de error con el mismo diseño; si hay sesión, conserva el menú."""
    token = request.cookies.get(cookie_name())
    db = new_session()
    try:
        try:
            loaded = auth_service.load_session(db, token)
        except Exception:  # noqa: BLE001 - si la BD falla, mostramos el error sin menú
            loaded = None
        ctx = AuthContext(user=loaded[1], session=loaded[0], token=token) if loaded else None
        return render(request, "error.html", ctx, None, status_code=status,
                      title=title, message=message)
    finally:
        db.close()
