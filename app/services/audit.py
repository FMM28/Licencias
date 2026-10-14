"""Bitácora de eventos (del cliente, del panel y de la consola)."""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.timeutil import utcnow
from app.models import AuditLog


def audit(db: Session, event: str, license_id: str | None = None, ip: str | None = None,
          detail: str | None = None, actor: str | None = None) -> None:
    """Agrega un evento a la sesión actual (el commit lo hace quien llama)."""
    db.add(AuditLog(ts=utcnow(), license_id=license_id, event=event, ip=ip,
                    detail=detail, actor=actor))


def list_audit(db: Session, *, license_id: str | None = None, event: str | None = None,
               actor: str | None = None, page: int = 1, per_page: int = 50
               ) -> tuple[list[AuditLog], int]:
    stmt = select(AuditLog)
    if license_id:
        stmt = stmt.where(AuditLog.license_id == license_id)
    if event:
        stmt = stmt.where(AuditLog.event == event)
    if actor:
        stmt = stmt.where(AuditLog.actor == actor)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(AuditLog.id.desc())
                      .limit(per_page).offset((max(page, 1) - 1) * per_page))
    return list(rows), total


def audit_events(db: Session) -> list[str]:
    return list(db.scalars(select(AuditLog.event).distinct().order_by(AuditLog.event)))
