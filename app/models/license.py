from datetime import datetime, timedelta

from sqlalchemy import JSON, Boolean, and_, or_, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import MYSQL_TABLE_ARGS, Base


class License(Base):
    __tablename__ = "licenses"
    __table_args__ = (MYSQL_TABLE_ARGS,)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # lic_xxxxxxxxxxxx
    # Solo guardamos el hash de la clave: si se filtra la BD, las claves no se filtran.
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    product: Mapped[str] = mapped_column(String(64), index=True)
    customer: Mapped[str] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    plan: Mapped[str] = mapped_column(String(20))  # perpetual | subscription | trial
    features: Mapped[list] = mapped_column(JSON, default=list)
    max_activations: Mapped[int] = mapped_column(Integer, default=1)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # UTC
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)

    activations: Mapped[list["Activation"]] = relationship(
        back_populates="license", cascade="all, delete-orphan"
    )


# Una activación recién emitida está "pendiente" hasta que el SDK confirma que pudo verificar
# el token. Mientras tanto ocupa un cupo (así el límite no se salta con peticiones en carrera),
# pero solo durante este tiempo: si nadie la confirma, deja de contar.
PENDING_TTL = timedelta(minutes=5)


class Activation(Base):
    __tablename__ = "activations"
    __table_args__ = (UniqueConstraint("license_id", "fingerprint",
                                       name="uq_activations_license_fingerprint"),
                      MYSQL_TABLE_ARGS)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    license_id: Mapped[str] = mapped_column(ForeignKey("licenses.id"), index=True)
    fingerprint: Mapped[str] = mapped_column(String(128))
    hostname: Mapped[str | None] = mapped_column(String(200), nullable=True)
    first_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    last_seen: Mapped[datetime] = mapped_column(DateTime)
    # None = pendiente de confirmar (o ya liberada). Se fija cuando el SDK confirma.
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    license: Mapped["License"] = relationship(back_populates="activations")

    @staticmethod
    def live_clause(now: datetime):
        """SQL: activa y (confirmada o pendiente todavía vigente)."""
        return and_(Activation.active.is_(True),
                    or_(Activation.confirmed_at.is_not(None),
                        Activation.last_seen > now - PENDING_TTL))

    def is_live(self, now: datetime) -> bool:
        return self.active and (self.confirmed_at is not None
                                or self.last_seen > now - PENDING_TTL)

    def is_pending(self, now: datetime) -> bool:
        return self.active and self.confirmed_at is None and self.last_seen > now - PENDING_TTL
