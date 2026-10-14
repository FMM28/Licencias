"""CRUD de licencias, estadísticas y bitácora a través de /api/admin."""
from datetime import timedelta

from app.core.timeutil import utcnow
from app.services import licenses as license_service


def make(panel, **over):
    body = {"product": "mi-app", "customer": "ACME", "plan": "subscription", "days": 365,
            "features": ["export"], "max_activations": 1, **over}
    r = panel.post("/api/admin/licenses", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_create_returns_key_once_and_it_works_with_the_sdk(env):
    panel = env.user_with("operator")
    created = make(panel, customer="Beta SA", features=["export", "api"], max_activations=2)
    key, lic = created["license_key"], created["license"]
    assert len(key) == 23 and key.count("-") == 3
    assert lic["status"] == "active" and lic["max_activations"] == 2 and lic["activations"] == []
    assert key not in panel.get(f"/api/admin/licenses/{lic['id']}").text   # nunca se vuelve a mostrar
    assert env.sdk().activate(key)["features"] == ["export", "api"]
    assert panel.get(f"/api/admin/licenses/{lic['id']}").json()["activations"][0]["active"] is True


def test_create_validation(env):
    panel = env.user_with("operator")
    bad = [
        {"product": "con espacios", "customer": "c", "plan": "perpetual"},
        {"product": "p", "customer": "", "plan": "perpetual"},
        {"product": "p", "customer": "c", "plan": "subscription"},                 # falta days
        {"product": "p", "customer": "c", "plan": "gratis"},
        {"product": "p", "customer": "c", "plan": "trial", "days": 0},
        {"product": "p", "customer": "c", "plan": "perpetual", "max_activations": 0},
        {"product": "p", "customer": "c", "plan": "perpetual", "features": ["mal feature"]},
        {"product": "p", "customer": "c" * 201, "plan": "perpetual"},
    ]
    for body in bad:
        assert panel.post("/api/admin/licenses", json=body).status_code == 422, body


def test_list_filters_search_and_pagination(env):
    panel = env.user_with("operator")
    for i in range(7):
        make(panel, customer=f"Cliente {i:02d}", product="alfa" if i % 2 else "beta")
    make(panel, customer="100%_real", product="alfa", plan="perpetual", days=None)

    def ids(**params):
        r = panel.get("/api/admin/licenses", params=params).json()
        return [x["customer"] for x in r["items"]], r["total"]

    assert ids()[1] == 8
    names, total = ids(product="alfa")
    assert total == 4 and all(n in names for n in ("Cliente 01", "100%_real"))
    assert ids(q="cliente 03") == (["Cliente 03"], 1)           # sin distinguir mayúsculas
    assert ids(q="100%_") == (["100%_real"], 1)                 # % y _ se tratan como texto literal
    assert ids(q="%") == (["100%_real"], 1)
    page1 = panel.get("/api/admin/licenses", params={"per_page": 3}).json()
    page3 = panel.get("/api/admin/licenses", params={"per_page": 3, "page": 3}).json()
    assert (len(page1["items"]), len(page3["items"]), page1["total"]) == (3, 2, 8)
    assert panel.get("/api/admin/licenses", params={"per_page": 1000}).status_code == 422
    assert panel.get("/api/admin/licenses", params={"status": "inventado"}).status_code == 422


def test_revoke_unrevoke_and_audit_trail_records_the_actor(env):
    panel = env.user_with("operator", "paola")
    lic_id = make(panel)["license"]["id"]
    r = panel.post(f"/api/admin/licenses/{lic_id}/revoke")
    assert r.json()["revoked"] is True and r.json()["status"] == "revoked"
    assert panel.post(f"/api/admin/licenses/{lic_id}/unrevoke").json()["status"] == "active"

    events = panel.get("/api/admin/audit", params={"license_id": lic_id}).json()["items"]
    assert [e["event"] for e in events] == ["unrevoked", "revoked", "license_created"]
    assert {e["actor"] for e in events} == {"paola"}


def test_extend_patch_and_release(env):
    panel = env.user_with("operator")
    lic_id = make(panel, days=10)["license"]["id"]
    before = panel.get(f"/api/admin/licenses/{lic_id}").json()["expires_at"]
    after = panel.post(f"/api/admin/licenses/{lic_id}/extend", json={"days": 30}).json()["expires_at"]
    assert after > before and after[:4] >= before[:4]
    assert panel.post(f"/api/admin/licenses/{lic_id}/extend", json={"days": 0}).status_code == 422

    patched = panel.patch(f"/api/admin/licenses/{lic_id}",
                          json={"max_activations": 3, "notes": "  paga por transferencia  "}).json()
    assert patched["max_activations"] == 3 and patched["notes"] == "paga por transferencia"
    assert panel.patch(f"/api/admin/licenses/{lic_id}", json={"max_activations": 0}).status_code == 422

    perpetual = make(panel, plan="perpetual", days=None)["license"]["id"]
    r = panel.post(f"/api/admin/licenses/{perpetual}/extend", json={"days": 5})
    assert r.status_code == 422 and "perpetua" in r.json()["error"]["message"]


def test_release_activation_frees_the_slot(env):
    panel = env.user_with("operator")
    created = make(panel)
    key, lic_id = created["license_key"], created["license"]["id"]
    env.sdk("a", "a" * 64).activate(key)
    assert panel.delete(f"/api/admin/licenses/{lic_id}/activations",
                        params={"fingerprint": "a" * 64}).json() == {"released": 1}
    env.sdk("b", "b" * 64).activate(key)                         # el cupo quedó libre


def test_unknown_license_is_404_everywhere(env):
    panel = env.user_with("operator")
    for method, url, kw in [("get", "/api/admin/licenses/lic_nope", {}),
                            ("post", "/api/admin/licenses/lic_nope/revoke", {}),
                            ("post", "/api/admin/licenses/lic_nope/extend", {"json": {"days": 3}}),
                            ("patch", "/api/admin/licenses/lic_nope", {"json": {"notes": "x"}}),
                            ("delete", "/api/admin/licenses/lic_nope/activations", {})]:
        r = getattr(panel, method)(url, **kw)
        assert r.status_code == 404 and r.json()["error"]["code"] == "not_found", url


def test_stats_match_listing_for_every_status(env, monkeypatch):
    """7 licencias en estados distintos: las cifras del tablero deben coincidir con los
    filtros del listado y con license_status() de cada una."""
    monkeypatch.setenv("LICENSE_EXPIRY_GRACE_DAYS", "3")
    panel = env.user_with("operator")
    make(panel, days=200)                                        # activa
    make(panel, days=10)                                         # por vencer
    make(panel, plan="perpetual", days=None)                     # activa (perpetua)
    revoked = make(panel, days=200)["license"]["id"]
    panel.post(f"/api/admin/licenses/{revoked}/revoke")          # revocada
    make(panel, days=1)                                          # tras 2 días: en gracia
    expired = make(panel, days=1)["license"]["id"]               # se vence del todo (abajo)
    env.sdk().activate(make(panel, days=100)["license_key"])     # activa, con 1 instalación
    env.clock.advance(days=2)               # (la sesión caduca por inactividad: se entra otra vez)
    with env.db() as db:
        lic = license_service.get_license(db, expired)
        lic.expires_at = utcnow() - timedelta(days=10)
        db.commit()
    panel = env.login("operator_user")

    stats = panel.get("/api/admin/stats").json()
    assert stats == {"total": 7, "active": 3, "expiring": 1, "grace": 1, "expired": 1,
                     "revoked": 1, "installations": 1}
    for status in ("active", "expiring", "grace", "expired", "revoked"):
        listed = panel.get("/api/admin/licenses", params={"status": status}).json()
        assert listed["total"] == stats[status], status
        assert all(item["status"] == status for item in listed["items"]), status


def test_audit_filters_and_pagination(env):
    panel = env.user_with("operator", "paola")
    for i in range(5):
        make(panel, customer=f"c{i}")
    page = panel.get("/api/admin/audit", params={"event": "license_created", "per_page": 2}).json()
    assert page["total"] == 5 and len(page["items"]) == 2
    assert panel.get("/api/admin/audit", params={"actor": "nadie"}).json()["total"] == 0
    # 5 altas + el inicio de sesión de paola: la bitácora también registra los accesos al panel
    assert panel.get("/api/admin/audit", params={"actor": "paola"}).json()["total"] == 6
    assert panel.get("/api/admin/audit", params={"actor": "paola",
                                                 "event": "license_created"}).json()["total"] == 5
    assert panel.get("/api/admin/audit", params={"per_page": 500}).status_code == 422


def test_docs_are_disabled_by_default(env):
    assert env.http.get("/docs").status_code == 404
    assert env.http.get("/openapi.json").status_code == 404
