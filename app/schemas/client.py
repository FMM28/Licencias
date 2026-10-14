"""Contratos de la API pública que consume el SDK (/v1)."""
from pydantic import BaseModel, Field


class ActivateIn(BaseModel):
    license_key: str = Field(min_length=8, max_length=64)
    product: str = Field(min_length=1, max_length=64)
    fingerprint: str = Field(min_length=16, max_length=128)
    hostname: str | None = Field(default=None, max_length=200)


class ValidateIn(BaseModel):
    license_key: str = Field(min_length=8, max_length=64)
    product: str | None = Field(default=None, max_length=64)
    fingerprint: str = Field(min_length=16, max_length=128)


class DeactivateIn(BaseModel):
    license_key: str = Field(min_length=8, max_length=64)
    fingerprint: str = Field(min_length=16, max_length=128)


class TokenOut(BaseModel):
    token: str
    token_expires_at: int          # unix ts: hasta cuándo sirve el token offline
    plan: str
    features: list[str]
    license_expires_at: int | None  # None = perpetua
