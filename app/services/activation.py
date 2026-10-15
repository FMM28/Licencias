"""Operaciones que hace el SDK instalado en el servidor del cliente:
activar, renovar el token y liberar la instalación."""
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import crypto
from app.core.config import get_settings
from app.core.errors import LicenseError
from app.core.timeutil import to_ts, utcnow
from app.models import Activation, License
from app.services.audit import audit
from app.services.licenses import effective_end, ensure_usable, hash_key


def build_token(lic: License, fingerprint: str) -> tuple[str, int]:
    settings = get_settings()
    now = utcnow()
    exp = now + timedelta(days=settings.token_ttl_days)
    end = effective_end(lic)
    if end is not None:
        exp = min(exp, end)
    exp_ts = to_ts(exp)
    payload = {
        "v": 1,
        "lic": lic.id,
        "product": lic.product,
        "customer": lic.customer,
        "plan": lic.plan,
        "features": lic.features,
        "fp": fingerprint,          # el token solo sirve en la máquina que lo pidió
        "iat": to_ts(now),
        "exp": exp_ts,              # vigencia del token (gracia offline)
        "lic_exp": to_ts(lic.expires_at),  # vencimiento real de la licencia (None = perpetua)
    }
    return crypto.sign_token(payload, crypto.load_signing_key(settings)), exp_ts


def _lookup(db: Session, key: str, lock: bool = False) -> License:
    stmt = select(License).where(License.key_hash == hash_key(key))
    if lock:
        # SELECT ... FOR UPDATE: dos activaciones simultáneas de la misma licencia se
        # serializan, así el límite de instalaciones no se puede saltar con peticiones en carrera.
        stmt = stmt.with_for_update()
    lic = db.scalar(stmt)
    if not lic:
        # Mensaje genérico: no revelamos si la clave "casi" existe.
        raise LicenseError("invalid_key", "Clave de licencia inválida", 404)
    return lic


def _sweep_unconfirmed(db: Session, lic: License) -> None:
    """Las activaciones pendientes que nadie confirmó a tiempo se cierran y quedan en la
    bitácora como fallidas (el SDK nunca llegó a usarlas)."""
    now = utcnow()
    for act in lic.activations:
        if act.active and act.confirmed_at is None and not act.is_pending(now):
            act.active = False
            audit(db, "activate_failed", lic.id, act.last_ip, "sin_confirmar")


def activate(db: Session, *, key: str, product: str, fingerprint: str,
             hostname: str | None, ip: str | None,
             two_phase: bool = False) -> tuple[License, str, int]:
    """Emite el token y reserva el cupo.

    Con `two_phase` la activación queda PENDIENTE y solo se registra como exitosa cuando el SDK
    llama a `confirm` (es decir, cuando logró verificar el token con su clave pública). Sin
    `two_phase` (SDK antiguo) se confirma de inmediato."""
    lic = _lookup(db, key, lock=True)
    try:
        ensure_usable(lic, product)
    except LicenseError as err:
        audit(db, "activate_denied", lic.id, ip, err.code)
        db.commit()
        raise
    _sweep_unconfirmed(db, lic)

    now = utcnow()
    act = next((a for a in lic.activations if a.fingerprint == fingerprint), None)
    if act is None or not act.active:
        others = sum(1 for a in lic.activations if a.is_live(now) and a.fingerprint != fingerprint)
        if others >= lic.max_activations:
            audit(db, "activate_denied", lic.id, ip, "activation_limit")
            db.commit()
            raise LicenseError(
                "activation_limit",
                f"Se alcanzó el límite de {lic.max_activations} instalación(es). "
                "Pide que liberen una activación.", 409)
    if act is None:
        act = Activation(license_id=lic.id, fingerprint=fingerprint, first_ip=ip,
                         created_at=now, last_seen=now, active=True)
        lic.activations.append(act)
    was_confirmed = act.active and act.confirmed_at is not None
    if not act.active:
        act.confirmed_at = None          # reactivación de una liberada: vuelve a ser pendiente
    act.active, act.last_seen, act.last_ip = True, now, ip
    act.hostname = hostname or act.hostname
    if not two_phase and not was_confirmed:
        act.confirmed_at = now
        audit(db, "activated", lic.id, ip, hostname)
    token, exp = build_token(lic, fingerprint)
    db.commit()
    return lic, token, exp


def confirm(db: Session, *, key: str, fingerprint: str, ip: str | None) -> None:
    """El SDK verificó el token: la activación pasa de pendiente a exitosa."""
    lic = _lookup(db, key, lock=True)
    _sweep_unconfirmed(db, lic)
    act = next((a for a in lic.activations if a.fingerprint == fingerprint and a.active), None)
    if act is None:
        db.commit()
        raise LicenseError("not_activated",
                           "La activación venció sin confirmarse; vuelve a activar", 409)
    if act.confirmed_at is None:
        act.confirmed_at = utcnow()
        audit(db, "activated", lic.id, ip, act.hostname)
    db.commit()


def abort(db: Session, *, key: str, fingerprint: str, reason: str, ip: str | None) -> None:
    """El SDK no pudo usar el token (p. ej. clave pública incorrecta): se libera el cupo y se
    registra como activación fallida. Nunca toca una instalación ya confirmada."""
    lic = _lookup(db, key, lock=True)
    for act in lic.activations:
        if act.fingerprint == fingerprint and act.active and act.confirmed_at is None:
            act.active = False
            audit(db, "activate_failed", lic.id, ip, reason)
    db.commit()


def refresh(db: Session, *, key: str, product: str | None, fingerprint: str,
            ip: str | None) -> tuple[License, str, int]:
    lic = _lookup(db, key)
    try:
        ensure_usable(lic, product)
    except LicenseError as err:
        audit(db, "validate_denied", lic.id, ip, err.code)
        db.commit()
        raise
    now = utcnow()
    act = next((a for a in lic.activations
                if a.fingerprint == fingerprint and a.is_live(now)), None)
    if act is None:
        raise LicenseError("not_activated", "Esta instalación no está activada", 403)
    if act.last_ip and ip and act.last_ip != ip:
        audit(db, "ip_changed", lic.id, ip, f"{act.last_ip} -> {ip}")
    act.last_seen, act.last_ip = utcnow(), ip
    token, exp = build_token(lic, fingerprint)
    db.commit()
    return lic, token, exp


def deactivate(db: Session, *, key: str, fingerprint: str, ip: str | None) -> None:
    lic = _lookup(db, key, lock=True)
    for act in lic.activations:
        if act.fingerprint == fingerprint and act.active:
            act.active = False
            audit(db, "deactivated", lic.id, ip)
    db.commit()
