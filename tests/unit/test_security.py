import pytest

from app.core import security


def test_password_hash_roundtrip():
    h = security.hash_password("una contraseña larga y buena")
    assert h.startswith("$argon2id$")
    assert security.verify_password(h, "una contraseña larga y buena")
    assert not security.verify_password(h, "otra distinta")
    assert not security.verify_password("no-es-un-hash", "x")


@pytest.mark.parametrize("password,fragment", [
    ("corta", "al menos"),
    ("aaaaaaaaaaaaaaaa", "repetitiva"),
    ("password1234", "predecible"),
    ("xxana-secretoxx", "contiene el usuario"),
    ("x" * 129, "no puede pasar"),
])
def test_password_policy_rejects(password, fragment):
    with pytest.raises(ValueError, match=fragment):
        security.validate_password(password, "ana")


def test_password_policy_accepts_long_passphrase():
    security.validate_password("correct-horse-battery", "ana")


def test_generated_password_is_valid_and_random():
    a, b = security.generate_password(), security.generate_password()
    assert a != b and a.count("-") == 3
    security.validate_password(a)


def test_role_permissions():
    viewer, operator, admin = (security.permissions_for(r) for r in security.ROLES)
    assert "licenses:write" not in viewer and "licenses:read" in viewer
    assert "licenses:write" in operator and "users:manage" not in operator
    assert "users:manage" in admin and operator < admin
    assert security.permissions_for("hacker") == frozenset()  # rol desconocido: nada


def test_session_tokens_are_unguessable_and_hashed():
    t1, t2 = security.new_token(), security.new_token()
    assert t1 != t2 and len(t1) >= 40
    assert security.hash_token(t1) != t1 and len(security.hash_token(t1)) == 64
