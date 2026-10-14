import pytest

from app.core import crypto, timeutil
from app.core.config import get_settings
from app.db.session import normalize_url


def test_token_sign_and_verify():
    priv, pub = crypto.generate_keypair()
    from nacl.signing import SigningKey
    token = crypto.sign_token({"a": 1, "z": [1, 2]}, SigningKey(crypto.b64d(priv)))
    assert crypto.verify_token(token, pub) == {"a": 1, "z": [1, 2]}


def test_token_rejects_tampering_wrong_key_and_garbage():
    from nacl.signing import SigningKey
    priv, pub = crypto.generate_keypair()
    _, other_pub = crypto.generate_keypair()
    token = crypto.sign_token({"plan": "basic"}, SigningKey(crypto.b64d(priv)))
    body, sig = token.split(".")

    forged = crypto.b64e(b'{"plan":"pro"}') + "." + sig
    for bad in (forged, token + "x", "no-es-un-token", "a.b.c", ""):
        with pytest.raises(ValueError):
            crypto.verify_token(bad, pub)
    with pytest.raises(ValueError):
        crypto.verify_token(token, other_pub)


@pytest.mark.parametrize("raw,expected", [
    ("mariadb://u:p@db.example/licenses",
     "mariadb+pymysql://u:p@db.example/licenses?charset=utf8mb4"),
    ("mysql://u:p@db/licenses", "mariadb+pymysql://u:p@db/licenses?charset=utf8mb4"),
    ("mariadb+pymysql://u:p@db/x?charset=latin1", "mariadb+pymysql://u:p@db/x?charset=latin1"),
])
def test_normalize_url(raw, expected):
    assert normalize_url(raw) == expected


@pytest.mark.parametrize("raw", ["sqlite:///./x.db", "postgresql://u:p@h/x", ""])
def test_normalize_url_rejects_other_engines(raw):
    with pytest.raises(ValueError):
        normalize_url(raw)


def test_clock_is_replaceable_and_strips_microseconds():
    from datetime import datetime, timezone
    timeutil.set_clock(lambda: datetime(2030, 1, 2, 3, 4, 5, 999999, tzinfo=timezone.utc))
    try:
        assert timeutil.utcnow() == datetime(2030, 1, 2, 3, 4, 5)
        assert timeutil.to_ts(timeutil.utcnow()) == int(datetime(
            2030, 1, 2, 3, 4, 5, tzinfo=timezone.utc).timestamp())
    finally:
        timeutil.reset_clock()
    assert timeutil.utcnow().year >= 2026


def test_settings_defaults_are_safe(monkeypatch):
    for name in ("LICENSE_COOKIE_SECURE", "LICENSE_ENABLE_DOCS", "LICENSE_AUTO_MIGRATE"):
        monkeypatch.delenv(name, raising=False)
    s = get_settings()
    assert s.cookie_secure is True and s.docs_enabled is False and s.auto_migrate is False
