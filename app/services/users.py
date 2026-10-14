"""Gestión de los usuarios del panel (alta, roles, activación y contraseñas)."""
import re

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import security
from app.core.timeutil import utcnow
from app.models import AdminUser
from app.services.audit import audit
from app.services.auth import destroy_user_sessions

USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")


def normalize_username(raw: str) -> str:
    username = (raw or "").strip().lower()
    if not USERNAME_RE.match(username):
        raise ValueError("El usuario debe tener de 3 a 64 caracteres: letras, números, "
                         "punto, guion o guion bajo")
    return username


def get_user(db: Session, user_id: int) -> AdminUser | None:
    return db.get(AdminUser, user_id)


def get_by_username(db: Session, username: str) -> AdminUser | None:
    return db.scalar(select(AdminUser).where(AdminUser.username == (username or "").strip().lower()))


def list_users(db: Session) -> list[AdminUser]:
    return list(db.scalars(select(AdminUser).order_by(AdminUser.username)))


def count_active_admins(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(AdminUser).where(
        AdminUser.role == "admin", AdminUser.is_active.is_(True))) or 0


def _require(db: Session, user_id: int) -> AdminUser:
    user = db.get(AdminUser, user_id)
    if not user:
        raise ValueError("Usuario no encontrado")
    return user


def _protect_last_admin(db: Session, user: AdminUser) -> None:
    if user.role == "admin" and user.is_active and count_active_admins(db) <= 1:
        raise ValueError("Debe quedar al menos un administrador activo")


def create_user(db: Session, *, username: str, password: str, role: str,
                must_change: bool = True, actor: str | None = None) -> AdminUser:
    username = normalize_username(username)
    if role not in security.ROLES:
        raise ValueError(f"Rol inválido: {role}")
    security.validate_password(password, username)
    now = utcnow()
    user = AdminUser(username=username, password_hash=security.hash_password(password),
                     role=role, is_active=True, must_change_password=must_change,
                     failed_attempts=0, created_at=now, password_changed_at=now)
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise ValueError("Ese usuario ya existe") from None
    audit(db, "user_created", detail=f"{username} ({role})", actor=actor)
    db.commit()
    return user


def set_role(db: Session, user_id: int, role: str, actor: str | None = None) -> AdminUser:
    user = _require(db, user_id)
    if role not in security.ROLES:
        raise ValueError(f"Rol inválido: {role}")
    if role != "admin":
        _protect_last_admin(db, user)
    user.role = role
    audit(db, "user_role", detail=f"{user.username} -> {role}", actor=actor)
    db.commit()
    return user


def set_active(db: Session, user_id: int, active: bool, actor: str | None = None) -> AdminUser:
    user = _require(db, user_id)
    if not active:
        _protect_last_admin(db, user)
    user.is_active = active
    if not active:
        destroy_user_sessions(db, user.id)
    audit(db, "user_enabled" if active else "user_disabled", detail=user.username, actor=actor)
    db.commit()
    return user


def reset_password(db: Session, user_id: int, new_password: str,
                   actor: str | None = None) -> AdminUser:
    """El admin define una contraseña temporal; el usuario deberá cambiarla al entrar."""
    user = _require(db, user_id)
    security.validate_password(new_password, user.username)
    user.password_hash = security.hash_password(new_password)
    user.must_change_password = True
    user.failed_attempts, user.locked_until = 0, None
    user.password_changed_at = utcnow()
    destroy_user_sessions(db, user.id)
    audit(db, "password_reset", detail=user.username, actor=actor)
    db.commit()
    return user


def change_password(db: Session, user: AdminUser, current: str, new: str,
                    keep_session_id: str | None = None) -> None:
    if not security.verify_password(user.password_hash, current):
        raise ValueError("La contraseña actual no es correcta")
    if current == new:
        raise ValueError("La contraseña nueva debe ser distinta de la actual")
    security.validate_password(new, user.username)
    user.password_hash = security.hash_password(new)
    user.must_change_password = False
    user.password_changed_at = utcnow()
    destroy_user_sessions(db, user.id, keep_id=keep_session_id)  # cierra las demás sesiones
    audit(db, "password_changed", detail=user.username, actor=user.username)
    db.commit()
