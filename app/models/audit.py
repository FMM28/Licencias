from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import MYSQL_TABLE_ARGS, Base


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (MYSQL_TABLE_ARGS,)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime, index=True)
    license_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    event: Mapped[str] = mapped_column(String(40))
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Quién hizo el cambio: "ana" (panel), "cli:root" (consola) o None (evento del cliente).
    actor: Mapped[str | None] = mapped_column(String(64), nullable=True)
