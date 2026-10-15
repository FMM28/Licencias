"""API de clientes (/v1) + SDK real + integración con Flask. El tiempo es simulado."""
import json

import pytest
from flask import Flask

from app.core import crypto
from app.core.config import get_settings
from app.services import licenses as license_service
from sdk.licensing_client import LicenseError, init_flask
from tests.conftest import PRODUCT, DeadHTTP


def test_activate_then_works_offline(env):
    lic_id, key = env.new_license()
    c = env.sdk()
    payload = c.activate(key)
    assert payload["lic"] == lic_id and payload["plan"] == "subscription"

    c._http = DeadHTTP()                      # se cae internet
    assert c.check()["features"] == ["export"]
    assert c.has_feature("export") and not c.has_feature("pro")

    from sqlalchemy import select
    from app.models import License
    with env.db() as db:
        row = db.scalar(select(License))
    assert key not in (row.key_hash, row.id)  # la clave en claro no se guarda


def test_invalid_key_and_wrong_product(env):
    _, key = env.new_license()
    with pytest.raises(LicenseError) as e:
        env.sdk().activate("AAAAA-BBBBB-CCCCC-DDDDD")
    assert e.value.code == "invalid_key"
    with pytest.raises(LicenseError) as e:
        env.sdk(product="otro-producto").activate(key)
    assert e.value.code == "product_mismatch"


def test_activation_limit_idempotent_release_and_deactivate(env):
    lic_id, key = env.new_license(max_activations=1)
    a, b = env.sdk("a", "a" * 64), env.sdk("b", "b" * 64)
    a.activate(key)
    a.activate(key)                           # reactivar la misma máquina no consume otro cupo
    with pytest.raises(LicenseError) as e:
        b.activate(key)
    assert e.value.code == "activation_limit"

    with env.db() as db:
        assert license_service.release_activation(db, lic_id, "a" * 64) == 1
    b.activate(key)                           # el admin liberó el cupo
    with pytest.raises(LicenseError):
        a.refresh()                           # a ya no está activada

    b.deactivate()                            # el propio cliente libera su cupo
    a.activate(key)


def test_revocation_takes_effect_on_next_refresh(env):
    lic_id, key = env.new_license()
    c = env.sdk()
    c.activate(key)
    with env.db() as db:
        license_service.set_revoked(db, lic_id, True)

    assert c.check()                          # token aún fresco: sigue funcionando
    env.clock.advance(days=6)                 # entra a la ventana de renovación
    with pytest.raises(LicenseError) as e:
        c.check()
    assert e.value.code == "revoked"
    with pytest.raises(LicenseError) as e:
        c.check()                             # y el token local ya se borró
    assert e.value.code == "not_activated"

    with pytest.raises(LicenseError) as e:
        env.sdk("otro", "c" * 64).activate(key)
    assert e.value.code == "revoked"


def test_subscription_grace_expiry_and_renewal(env):
    lic_id, key = env.new_license(days=30)
    c = env.sdk()
    c.activate(key)

    env.clock.advance(days=31)                # venció hace 1 día, dentro de los 3 de gracia
    p = c.check()
    assert p["exp"] <= p["lic_exp"] + 3 * 86400

    env.clock.advance(days=3)                 # día 34: fuera de la gracia
    with pytest.raises(LicenseError) as e:
        c.check()
    assert e.value.code == "expired"

    with env.db() as db:                      # el cliente paga y renuevas a mano
        license_service.extend_license(db, lic_id, 30)
    c.refresh()
    assert c.check()["plan"] == "subscription"


def test_perpetual_license_keeps_working_with_refresh(env):
    _, key = env.new_license(plan="perpetual", days=None)
    c = env.sdk()
    assert c.activate(key)["lic_exp"] is None
    for _ in range(5):
        env.clock.advance(days=100)           # 500 días en total, renovando cada ciclo
        assert c.check()["lic_exp"] is None


def test_offline_grace_expires(env):
    _, key = env.new_license()
    c = env.sdk()
    c.activate(key)
    c._http = DeadHTTP()
    env.clock.advance(days=3)
    assert c.check()                          # dentro de los 7 días de gracia
    env.clock.advance(days=5)
    with pytest.raises(LicenseError) as e:
        c.check()
    assert e.value.code == "offline_grace_expired"


def test_token_bound_to_machine_and_tamper_proof(env):
    from nacl.signing import SigningKey
    import time
    _, key = env.new_license()
    a = env.sdk("a", "a" * 64)
    a.activate(key)
    token = json.loads(a.storage.read_text())["token"]

    # 1) copiar el token a otra máquina no sirve
    b = env.sdk("b", "b" * 64)
    b.storage.write_text(json.dumps({"license_key": key, "token": token}))
    with pytest.raises(LicenseError) as e:
        b.check()
    assert e.value.code == "fingerprint_mismatch"

    # 2) editar el payload (agregar una feature) invalida la firma
    body, sig = token.split(".")
    payload = json.loads(crypto.b64d(body))
    payload["features"] = ["export", "pro"]
    forged = crypto.b64e(json.dumps(payload).encode()) + "." + sig
    a.storage.write_text(json.dumps({"license_key": key, "token": forged}))
    with pytest.raises(LicenseError) as e:
        a.check()
    assert e.value.code == "invalid_token"

    # 3) token firmado con OTRA clave privada tampoco
    other_priv, _ = crypto.generate_keypair()
    fake = crypto.sign_token({**payload, "fp": "a" * 64, "exp": int(time.time()) + 999999,
                              "product": PRODUCT}, SigningKey(crypto.b64d(other_priv)))
    a.storage.write_text(json.dumps({"license_key": key, "token": fake}))
    with pytest.raises(LicenseError) as e:
        a.check()
    assert e.value.code == "invalid_token"


def test_clock_rollback_detected(env):
    _, key = env.new_license()
    c = env.sdk()
    c.activate(key)
    c._http = DeadHTTP()
    env.clock.advance(days=3)
    assert c.check()
    env.clock.advance(days=-2)                # alguien retrocede el reloj
    with pytest.raises(LicenseError) as e:
        c.check()
    assert e.value.code == "clock_tampered"


def test_flask_integration(env):
    _, key = env.new_license(features=["export"])
    c = env.sdk()
    flask_app = Flask(__name__)

    @flask_app.route("/")
    def index():
        return "hola"

    @flask_app.route("/export")
    @c.requires_feature("export")
    def export():
        return "csv"

    @flask_app.route("/pro")
    @c.requires_feature("pro")
    def pro():
        return "pro"

    init_flask(flask_app, c, background_refresh=False)
    web = flask_app.test_client()

    assert web.get("/").status_code == 403                   # sin activar: app bloqueada
    assert web.get("/license/status").status_code == 403
    assert web.post("/license/activate", json={"license_key": "XXXXX-XXXXX-XXXXX-XXXXX"}
                    ).status_code == 400
    assert web.post("/license/activate", json={"license_key": key}).status_code == 200
    assert web.get("/").status_code == 200
    assert web.get("/export").status_code == 200
    r = web.get("/pro")
    assert r.status_code == 403 and r.get_json()["error"] == "feature_not_licensed"
    assert web.get("/license/status").get_json()["valid"] is True


def test_client_api_rate_limit(env, monkeypatch):
    monkeypatch.setenv("LICENSE_RATE_LIMIT", "3")
    codes = [env.http.post("/v1/validate", json={
        "license_key": "AAAAA-BBBBB-CCCCC-DDDDD", "fingerprint": "f" * 32}).status_code
        for _ in range(5)]
    assert codes == [404, 404, 404, 429, 429]


def test_client_api_error_shape_and_input_validation(env):
    r = env.http.post("/v1/activate", json={"license_key": "x"})        # faltan campos
    assert r.status_code == 422
    r = env.http.post("/v1/validate", json={"license_key": "AAAAA-BBBBB-CCCCC-DDDDD",
                                            "fingerprint": "f" * 32})
    assert r.status_code == 404
    assert r.json() == {"error": {"code": "invalid_key", "message": "Clave de licencia inválida"}}


def test_public_key_matches_signing_key(env):
    assert env.http.get("/v1/public-key").json()["public_key"] == env.pub


def test_health_endpoints(env):
    assert env.http.get("/health").json() == {"status": "ok"}
    r = env.http.get("/health/ready")
    assert r.status_code == 200 and r.json()["schema"] == "0003"


def test_settings_used_by_tokens(env):
    assert get_settings().token_ttl_days == 7


def test_wrong_public_key_is_reported_clearly_and_releases_the_slot(env):
    from nacl.signing import SigningKey

    from app.core.crypto import b64e
    from app.models import Activation
    from sdk.licensing_client import LicenseError

    _, key = env.new_license(max_activations=1)
    sdk = env.sdk("wrong")
    sdk.public_key = b64e(bytes(SigningKey.generate().verify_key))   # otra clave, bien formada
    with pytest.raises(LicenseError) as exc:
        sdk.activate(key)
    assert exc.value.code == "bad_signature" and "clave pública" in exc.value.message
    assert not sdk.storage.exists()                                  # no se guardó nada
    with env.db() as db:                                             # el cupo quedó libre
        assert db.query(Activation).filter(Activation.active.is_(True)).count() == 0
    env.sdk("good").activate(key)                                    # y la licencia sigue usable


def test_malformed_public_key_is_reported_clearly(env):
    from sdk.licensing_client import LicenseError

    _, key = env.new_license()
    sdk = env.sdk("bad")
    sdk.public_key = "esto-no-es-una-clave"
    with pytest.raises(LicenseError) as exc:
        sdk.activate(key)
    assert exc.value.code == "invalid_public_key"


# ------------------------------------------------------------- activación en dos fases

def events(env, lic_id):
    from sqlalchemy import select

    from app.models import AuditLog
    with env.db() as db:
        return [(e.event, e.detail) for e in db.scalars(
            select(AuditLog).where(AuditLog.license_id == lic_id).order_by(AuditLog.id))]


def installs(env, lic_id):
    from app.services import licenses as svc
    with env.db() as db:
        return svc.active_installs(svc.get_license(db, lic_id))


def test_failed_client_verification_is_logged_as_failed_never_as_activated(env):
    from nacl.signing import SigningKey

    from app.core.crypto import b64e
    lic_id, key = env.new_license(max_activations=1)
    sdk = env.sdk("wrong")
    sdk.public_key = b64e(bytes(SigningKey.generate().verify_key))
    with pytest.raises(LicenseError):
        sdk.activate(key)
    names = [e for e, _ in events(env, lic_id)]
    assert "activated" not in names
    assert ("activate_failed", "bad_signature") in events(env, lic_id)
    assert installs(env, lic_id) == 0


def test_successful_activation_is_logged_once_and_counts(env):
    lic_id, key = env.new_license()
    env.sdk("ok").activate(key)
    assert [e for e, _ in events(env, lic_id)].count("activated") == 1
    assert installs(env, lic_id) == 1


def test_pending_activation_holds_the_slot_then_expires_and_is_logged_failed(env):
    lic_id, key = env.new_license(max_activations=1)
    body = {"license_key": key, "product": PRODUCT, "fingerprint": "a" * 32, "two_phase": True}
    assert env.new_http().post("/v1/activate", json=body).status_code == 200
    assert "activated" not in [e for e, _ in events(env, lic_id)]
    other = {**body, "fingerprint": "b" * 32}
    assert env.new_http().post("/v1/activate", json=other).status_code == 409   # cupo reservado
    env.clock.advance(minutes=6)                                                # nadie confirmó
    assert installs(env, lic_id) == 0
    assert env.new_http().post("/v1/activate", json=other).status_code == 200   # cupo libre
    assert ("activate_failed", "sin_confirmar") in events(env, lic_id)
    late = env.new_http().post("/v1/activate/confirm",
                               json={"license_key": key, "fingerprint": "a" * 32})
    assert late.status_code == 409


def test_abort_never_releases_a_confirmed_installation(env):
    lic_id, key = env.new_license()
    env.sdk("ok").activate(key)
    fp = env.sdk("ok").fingerprint()
    r = env.new_http().post("/v1/activate/abort",
                            json={"license_key": key, "fingerprint": fp, "reason": "bad_signature"})
    assert r.status_code == 200 and installs(env, lic_id) == 1


def test_legacy_clients_without_two_phase_are_confirmed_immediately(env):
    lic_id, key = env.new_license()
    r = env.new_http().post("/v1/activate", json={
        "license_key": key, "product": PRODUCT, "fingerprint": "c" * 32})
    assert r.status_code == 200 and installs(env, lic_id) == 1
    assert [e for e, _ in events(env, lic_id)].count("activated") == 1
