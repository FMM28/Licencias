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
    assert r.status_code == 200 and r.json()["schema"] == "0002"


def test_settings_used_by_tokens(env):
    assert get_settings().token_ttl_days == 7
