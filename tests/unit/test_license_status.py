"""license_status() sobre objetos en memoria (sin base de datos)."""
from datetime import timedelta

import pytest

from app.core.timeutil import utcnow
from app.models import License
from app.services.licenses import license_status


def lic(plan="subscription", delta_days=None, revoked=False):
    expires = None if delta_days is None else utcnow() + timedelta(days=delta_days)
    return License(id="lic_x", key_hash="h", product="p", customer="c", plan=plan,
                   features=[], max_activations=1, expires_at=expires, revoked=revoked,
                   created_at=utcnow())


@pytest.mark.parametrize("kwargs,expected", [
    (dict(plan="perpetual"), "active"),
    (dict(delta_days=200), "active"),
    (dict(delta_days=10), "expiring"),
    (dict(delta_days=0.5), "expiring"),
    (dict(delta_days=-1), "grace"),            # suscripción: 3 días de gracia
    (dict(delta_days=-4), "expired"),
    (dict(plan="trial", delta_days=-1), "expired"),  # las pruebas no tienen gracia
    (dict(plan="perpetual", revoked=True), "revoked"),
    (dict(delta_days=200, revoked=True), "revoked"),
    (dict(delta_days=-400, revoked=True), "revoked"),
])
def test_status(monkeypatch, kwargs, expected):
    monkeypatch.setenv("LICENSE_EXPIRY_GRACE_DAYS", "3")
    assert license_status(lic(**kwargs)) == expected
