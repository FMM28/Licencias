"""Utilidades comunes a las rutas del panel."""
import re

from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.errors import LicenseError, PageNotFound
from app.models import License
from app.services import licenses as license_service

PER_PAGE = 25
PRODUCT_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
FEATURE_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,40}$")


def redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)  # 303: el navegador sigue con GET


def safe_next(value: str | None) -> str:
    """Solo rutas internas del panel (evita open redirect)."""
    if value and value.startswith("/admin") and not value.startswith("//") and "\\" not in value:
        return value
    return ""


def to_int(value: str, label: str, *, minimum: int = 1, maximum: int = 100000) -> int:
    try:
        n = int(str(value).strip())
    except ValueError:
        raise ValueError(f"{label} debe ser un número entero") from None
    if not minimum <= n <= maximum:
        raise ValueError(f"{label} debe estar entre {minimum} y {maximum}")
    return n


def parse_features(raw: str) -> list[str]:
    items = [f.strip() for f in raw.replace("\n", ",").split(",") if f.strip()]
    if len(items) > 30:
        raise ValueError("Máximo 30 features")
    for item in items:
        if not FEATURE_RE.match(item):
            raise ValueError(f"Feature inválida: «{item[:40]}» (letras, números y . _ : -)")
    return list(dict.fromkeys(items))  # sin duplicados, conservando el orden


def get_license_or_404(db: Session, license_id: str) -> License:
    try:
        return license_service.get_license(db, license_id)
    except LicenseError:
        raise PageNotFound() from None
