"""Contratos de la API de administración (/api/admin)."""
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

Product = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z0-9_.-]{1,64}$")]
Feature = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z0-9_.:-]{1,40}$")]
Role = Literal["viewer", "operator", "admin"]
Status = Literal["active", "expiring", "grace", "expired", "revoked"]


# ---------------------------------------------------------------- sesión

class LoginIn(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=256)


class PasswordChangeIn(BaseModel):
    current: str = Field(max_length=256)
    new: str = Field(max_length=256)


class UserOut(BaseModel):
    id: int
    username: str
    role: str
    is_active: bool
    must_change_password: bool
    last_login_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class MeOut(BaseModel):
    user: UserOut
    permissions: list[str]
    csrf_token: str  # enviar en la cabecera X-CSRF-Token en todo POST/PATCH/DELETE


# ---------------------------------------------------------------- licencias

class LicenseCreateIn(BaseModel):
    product: Product
    customer: str = Field(min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=200)
    plan: Literal["perpetual", "subscription", "trial"] = "subscription"
    features: list[Feature] = Field(default_factory=list, max_length=30)
    max_activations: int = Field(default=1, ge=1, le=1000)
    days: int | None = Field(default=None, ge=1, le=3650)
    notes: str | None = Field(default=None, max_length=2000)


class LicenseUpdateIn(BaseModel):
    max_activations: int | None = Field(default=None, ge=1, le=1000)
    notes: str | None = Field(default=None, max_length=2000)


class ExtendIn(BaseModel):
    days: int = Field(ge=1, le=3650)


class ActivationOut(BaseModel):
    fingerprint: str
    hostname: str | None
    last_ip: str | None
    active: bool                     # ocupa un cupo ahora mismo
    state: Literal["active", "pending", "unconfirmed", "released"]
    last_seen: datetime

    model_config = {"from_attributes": True}


class LicenseOut(BaseModel):
    id: str
    product: str
    customer: str
    email: str | None
    plan: str
    features: list[str]
    max_activations: int
    expires_at: datetime | None
    revoked: bool
    status: str
    notes: str | None
    created_at: datetime
    activations: list[ActivationOut] = []


class LicenseCreatedOut(BaseModel):
    license: LicenseOut
    license_key: str  # se muestra una sola vez


class LicensePage(BaseModel):
    items: list[LicenseOut]
    total: int
    page: int
    per_page: int


class StatsOut(BaseModel):
    total: int
    active: int
    expiring: int
    grace: int
    expired: int
    revoked: int
    installations: int


# ---------------------------------------------------------------- bitácora

class AuditOut(BaseModel):
    id: int
    ts: datetime
    license_id: str | None
    event: str
    detail: str | None
    ip: str | None
    actor: str | None

    model_config = {"from_attributes": True}


class AuditPage(BaseModel):
    items: list[AuditOut]
    total: int
    page: int
    per_page: int


# ---------------------------------------------------------------- usuarios del panel

class UserCreateIn(BaseModel):
    username: str = Field(max_length=64)
    role: Role = "viewer"
    password: str | None = Field(default=None, max_length=256)  # vacío = se genera una temporal


class UserCreatedOut(BaseModel):
    user: UserOut
    temporary_password: str | None  # solo si se generó; se muestra una vez


class UserUpdateIn(BaseModel):
    role: Role | None = None
    is_active: bool | None = None


class PasswordResetIn(BaseModel):
    password: str | None = Field(default=None, max_length=256)


class PasswordResetOut(BaseModel):
    temporary_password: str | None
