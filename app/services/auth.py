"""Inicio de sesión y sesiones del panel (todo en base de datos)."""
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core import security
from app.core.config import get_settings
from app.core.errors import AuthError
from app.core.timeutil import utcnow
from app.models import AdminSession, AdminUser
from app.services.audit import audit

GENERIC_LOGIN_ERROR = "Usuario o contraseña incorrectos, o cuenta bloqueada temporalmente."


def authenticate(db: Session, username: str, password: str, ip: str | None,
                 user_agent: str | None) -> tuple[AdminUser, str, AdminSession]:
    """Valida credenciales y abre una sesión. Todas las fallas devuelven el mismo mensaje
    (no se puede averiguar qué usuarios existen ni cuáles están bloqueados o desactivados)."""
    settings = get_settings()
    now = utcnow()
    username = (username or "").strip().lower()[:64]
    password = (password or "")[:security.MAX_PASSWORD_LENGTH + 1]
    user = db.scalar(select(AdminUser).where(AdminUser.username == username))

    if user is None:
        security.burn_time(password)
        audit(db, "admin_login_failed", ip=ip, detail=f"usuario desconocido: {username}")
        db.commit()
        raise AuthError(GENERIC_LOGIN_ERROR)

    if user.locked_until and user.locked_until > now:
        security.burn_time(password)
        audit(db, "admin_login_blocked", ip=ip, detail=username, actor=username)
        db.commit()
        raise AuthError(GENERIC_LOGIN_ERROR)

    if not security.verify_password(user.password_hash, password):
        user.failed_attempts += 1
        detail = f"intento {user.failed_attempts}/{settings.login_max_failures}"
        if user.failed_attempts >= settings.login_max_failures:
            user.locked_until = now + timedelta(minutes=settings.login_lock_minutes)
            user.failed_attempts = 0
            detail = f"cuenta bloqueada {settings.login_lock_minutes} min"
        audit(db, "admin_login_failed", ip=ip, detail=detail, actor=username)
        db.commit()
        raise AuthError(GENERIC_LOGIN_ERROR)

    if not user.is_active:
        audit(db, "admin_login_failed", ip=ip, detail="cuenta desactivada", actor=username)
        db.commit()
        raise AuthError(GENERIC_LOGIN_ERROR)

    user.failed_attempts, user.locked_until, user.last_login_at = 0, None, now
    if security.needs_rehash(user.password_hash):
        user.password_hash = security.hash_password(password)
    purge_expired(db)
    token, session = create_session(db, user, ip, user_agent)
    audit(db, "admin_login", ip=ip, actor=user.username)
    db.commit()
    return user, token, session


def create_session(db: Session, user: AdminUser, ip: str | None,
                   user_agent: str | None) -> tuple[str, AdminSession]:
    """Sesión nueva en cada login (nunca se reutiliza una anterior: evita session fixation)."""
    now = utcnow()
    token = security.new_token()
    session = AdminSession(
        id=security.hash_token(token), user_id=user.id, csrf_token=security.new_token(),
        created_at=now, last_seen=now,
        expires_at=now + timedelta(hours=get_settings().session_max_hours),
        ip=ip, user_agent=(user_agent or "")[:255] or None, flash=None)
    db.add(session)
    return token, session


def load_session(db: Session, token: str | None) -> tuple[AdminSession, AdminUser] | None:
    """Devuelve (sesión, usuario) si el token es válido, no expiró y el usuario sigue activo."""
    if not token or len(token) > 200:
        return None
    session = db.get(AdminSession, security.hash_token(token))
    if session is None:
        return None
    now = utcnow()
    idle = timedelta(minutes=get_settings().session_idle_minutes)
    user = session.user
    if session.expires_at <= now or session.last_seen + idle <= now or not user.is_active:
        db.delete(session)
        db.commit()
        return None
    if (now - session.last_seen).total_seconds() >= 60:  # no escribimos en cada petición
        session.last_seen = now
        db.commit()
    return session, user


def destroy_session(db: Session, token: str | None) -> None:
    if token:
        db.execute(delete(AdminSession).where(AdminSession.id == security.hash_token(token)))
        db.commit()


def destroy_user_sessions(db: Session, user_id: int, keep_id: str | None = None) -> int:
    """Cierra todas las sesiones de un usuario (menos `keep_id`). No hace commit."""
    stmt = delete(AdminSession).where(AdminSession.user_id == user_id)
    if keep_id:
        stmt = stmt.where(AdminSession.id != keep_id)
    return db.execute(stmt).rowcount or 0


def list_sessions(db: Session, user_id: int) -> list[AdminSession]:
    return list(db.scalars(select(AdminSession).where(AdminSession.user_id == user_id)
                           .order_by(AdminSession.last_seen.desc())))


def purge_expired(db: Session) -> None:
    now = utcnow()
    idle = timedelta(minutes=get_settings().session_idle_minutes)
    db.execute(delete(AdminSession).where(
        (AdminSession.expires_at <= now) | (AdminSession.last_seen <= now - idle)))
