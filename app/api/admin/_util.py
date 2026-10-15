from contextlib import contextmanager

from app.core.errors import ApiError
from app.core.timeutil import utcnow
from app.models import License
from app.schemas.admin import ActivationOut, LicenseOut
from app.services import licenses as license_service


@contextmanager
def invalid_as_422():
    """Convierte los ValueError de los servicios (validaciones de negocio) en HTTP 422."""
    try:
        yield
    except ValueError as exc:
        raise ApiError("invalid", str(exc), 422) from exc


def _activation_out(a) -> ActivationOut:
    now = utcnow()
    state = ("pending" if a.is_pending(now) else "active" if a.is_live(now)
             else "unconfirmed" if a.active else "released")
    return ActivationOut(fingerprint=a.fingerprint, hostname=a.hostname, last_ip=a.last_ip,
                         active=a.is_live(now), state=state, last_seen=a.last_seen)


def license_out(lic: License) -> LicenseOut:
    return LicenseOut(
        id=lic.id, product=lic.product, customer=lic.customer, email=lic.email, plan=lic.plan,
        features=lic.features or [], max_activations=lic.max_activations,
        expires_at=lic.expires_at, revoked=lic.revoked, status=license_service.license_status(lic),
        notes=lic.notes, created_at=lic.created_at,
        activations=[_activation_out(a) for a in lic.activations])
