"""Licencias: alta, consulta, renovación, revocación y cálculo de estado."""
import hashlib
import secrets
from datetime import datetime, timedelta

from sqlalchemy import and_, func, not_, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.core.errors import LicenseError
from app.core.timeutil import utcnow
from app.models import Activation, License
from app.services.audit import audit

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sin 0/O/1/I para evitar confusiones
PLANS = ("perpetual", "subscription", "trial")
STATUSES = ("active", "expiring", "grace", "expired", "revoked")
EXPIRING_DAYS = 30


# ---------------------------------------------------------------- claves

def generate_key() -> str:
    groups = ["".join(secrets.choice(ALPHABET) for _ in range(5)) for _ in range(4)]
    return "-".join(groups)


def normalize_key(key: str) -> str:
    return key.strip().upper().replace(" ", "")


def hash_key(key: str) -> str:
    return hashlib.sha256(normalize_key(key).encode()).hexdigest()


# ---------------------------------------------------------------- altas y cambios

def create_license(db: Session, *, product: str, customer: str, email: str | None = None,
                   plan: str = "subscription", features: list[str] | None = None,
                   max_activations: int = 1, days: int | None = None,
                   notes: str | None = None, actor: str | None = None
                   ) -> tuple[License, str]:
    """Crea una licencia. Devuelve (licencia, clave_en_claro). La clave solo se ve ahora."""
    if plan not in PLANS:
        raise ValueError(f"plan debe ser uno de {PLANS}")
    if max_activations < 1:
        raise ValueError("max_activations debe ser al menos 1")
    if plan == "perpetual":
        expires_at = None
    else:
        if not days or days < 1:
            raise ValueError("los planes 'subscription' y 'trial' requieren days")
        expires_at = utcnow() + timedelta(days=days)
    key = generate_key()
    lic = License(
        id="lic_" + secrets.token_hex(6), key_hash=hash_key(key), product=product.strip(),
        customer=customer.strip(), email=(email or "").strip() or None, plan=plan,
        features=features or [], max_activations=max_activations, expires_at=expires_at,
        notes=(notes or "").strip() or None, revoked=False, created_at=utcnow(),
    )
    db.add(lic)
    audit(db, "license_created", lic.id, detail=f"{lic.customer} / {plan}", actor=actor)
    db.commit()
    return lic, key


def get_license(db: Session, license_id: str) -> License:
    lic = db.get(License, license_id)
    if not lic:
        raise LicenseError("not_found", "Licencia no encontrada", 404)
    return lic


def set_revoked(db: Session, license_id: str, revoked: bool,
                actor: str | None = None) -> License:
    lic = get_license(db, license_id)
    lic.revoked = revoked
    audit(db, "revoked" if revoked else "unrevoked", lic.id, actor=actor)
    db.commit()
    return lic


def extend_license(db: Session, license_id: str, days: int,
                   actor: str | None = None) -> License:
    """Renueva una suscripción: suma días desde el vencimiento (o desde hoy si ya venció)."""
    lic = get_license(db, license_id)
    if lic.expires_at is None:
        raise ValueError("la licencia es perpetua, no tiene vencimiento")
    if days < 1:
        raise ValueError("days debe ser al menos 1")
    base = max(lic.expires_at, utcnow())
    lic.expires_at = base + timedelta(days=days)
    audit(db, "extended", lic.id, detail=f"+{days}d -> {lic.expires_at:%Y-%m-%d}", actor=actor)
    db.commit()
    return lic


def set_max_activations(db: Session, license_id: str, n: int,
                        actor: str | None = None) -> License:
    if n < 1:
        raise ValueError("el máximo de activaciones debe ser al menos 1")
    lic = get_license(db, license_id)
    lic.max_activations = n
    audit(db, "max_activations", lic.id, detail=str(n), actor=actor)
    db.commit()
    return lic


def update_notes(db: Session, license_id: str, notes: str | None,
                 actor: str | None = None) -> License:
    lic = get_license(db, license_id)
    lic.notes = (notes or "").strip() or None
    audit(db, "notes_updated", lic.id, actor=actor)
    db.commit()
    return lic


def release_activation(db: Session, license_id: str, fingerprint: str | None = None,
                       actor: str | None = None) -> int:
    """Libera una activación (o todas) para que el cliente pueda mover su instalación."""
    lic = get_license(db, license_id)
    n = 0
    for act in lic.activations:
        if act.active and (fingerprint is None or act.fingerprint == fingerprint):
            act.active = False
            n += 1
    audit(db, "released", lic.id, detail=f"{n} activación(es)", actor=actor)
    db.commit()
    return n


# ---------------------------------------------------------------- estado

def active_installs(lic: License) -> int:
    return sum(1 for a in lic.activations if a.active)


def active_count(db: Session, license_id: str) -> int:
    return db.scalar(select(func.count()).select_from(Activation).where(
        Activation.license_id == license_id, Activation.active.is_(True))) or 0


def effective_end(lic: License) -> datetime | None:
    """Fecha hasta la que el servidor acepta la licencia (vencimiento + gracia)."""
    if lic.expires_at is None:
        return None
    grace = get_settings().expiry_grace_days if lic.plan == "subscription" else 0
    return lic.expires_at + timedelta(days=grace)


def license_status(lic: License) -> str:
    """active | expiring | grace | expired | revoked"""
    if lic.revoked:
        return "revoked"
    if lic.expires_at is None:
        return "active"
    now = utcnow()
    if now <= lic.expires_at:
        return "expiring" if lic.expires_at - now <= timedelta(days=EXPIRING_DAYS) else "active"
    end = effective_end(lic)
    return "grace" if end and end > lic.expires_at and now <= end else "expired"


def ensure_usable(lic: License, product: str | None = None) -> None:
    if lic.revoked:
        raise LicenseError("revoked", "La licencia fue revocada")
    if product is not None and lic.product != product:
        raise LicenseError("product_mismatch", "Esta licencia no corresponde a este producto")
    end = effective_end(lic)
    if end is not None and utcnow() > end:
        raise LicenseError("expired", "La licencia expiró. Contacta a tu proveedor para renovarla")


# ---------------------------------------------------------------- consultas del panel

def _status_clause(status: str):
    """Misma lógica que license_status(), pero como condición SQL (para filtrar y contar)."""
    now = utcnow()
    grace = timedelta(days=get_settings().expiry_grace_days)
    soon = now + timedelta(days=EXPIRING_DAYS)
    live = License.revoked.is_(False)
    in_grace = and_(License.plan == "subscription", License.expires_at < now,
                    License.expires_at >= now - grace)
    if status == "revoked":
        return License.revoked.is_(True)
    if status == "active":
        return and_(live, or_(License.expires_at.is_(None), License.expires_at > soon))
    if status == "expiring":
        return and_(live, License.expires_at >= now, License.expires_at <= soon)
    if status == "grace":
        return and_(live, in_grace)
    if status == "expired":
        return and_(live, License.expires_at < now, not_(in_grace))
    raise ValueError(f"estado desconocido: {status}")


def _like(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def list_licenses_page(db: Session, *, q: str | None = None, status: str | None = None,
                       product: str | None = None, page: int = 1, per_page: int = 25,
                       sort: str = "created") -> tuple[list[License], int]:
    """Listado filtrado y paginado: (licencias con sus activaciones, total).
    sort: "created" (más nuevas primero) o "expires" (las que vencen antes, primero)."""
    stmt = select(License)
    if q and q.strip():
        like = _like(q.strip())
        stmt = stmt.where(or_(*(col.ilike(like, escape="\\") for col in
                                (License.customer, License.email, License.id, License.product))))
    if status in STATUSES:
        stmt = stmt.where(_status_clause(status))
    if product:
        stmt = stmt.where(License.product == product)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    order = ((License.expires_at.asc(), License.id) if sort == "expires"
             else (License.created_at.desc(), License.id))
    rows = db.scalars(stmt.options(selectinload(License.activations)).order_by(*order)
                      .limit(per_page).offset((max(page, 1) - 1) * per_page))
    return list(rows), total


def list_products(db: Session) -> list[str]:
    return list(db.scalars(select(License.product).distinct().order_by(License.product)))


def stats(db: Session) -> dict[str, int]:
    out = {"total": db.scalar(select(func.count()).select_from(License)) or 0}
    for st in STATUSES:
        out[st] = db.scalar(select(func.count()).select_from(License)
                            .where(_status_clause(st))) or 0
    out["installations"] = db.scalar(select(func.count()).select_from(Activation)
                                     .where(Activation.active.is_(True))) or 0
    return out
