from contextlib import contextmanager

from app.core.errors import ApiError
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


def license_out(lic: License) -> LicenseOut:
    return LicenseOut(
        id=lic.id, product=lic.product, customer=lic.customer, email=lic.email, plan=lic.plan,
        features=lic.features or [], max_activations=lic.max_activations,
        expires_at=lic.expires_at, revoked=lic.revoked, status=license_service.license_status(lic),
        notes=lic.notes, created_at=lic.created_at,
        activations=[ActivationOut.model_validate(a, from_attributes=True)
                     for a in lic.activations])
