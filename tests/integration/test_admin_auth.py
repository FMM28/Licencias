"""Autenticación, sesiones, CSRF y autorización por rol (API JSON y páginas)."""
import hashlib

import pytest
from sqlalchemy import select

from app.models import AdminSession, AuditLog
from tests.conftest import COOKIE, PASSWORD


def login_raw(env, username="ana", password=PASSWORD, client=None):
    client = client or env.new_http()
    r = client.post("/api/admin/auth/login", json={"username": username, "password": password})
    return client, r


# ------------------------------------------------------------------ login

def test_login_returns_user_permissions_and_csrf(env):
    env.make_user("ana", "operator")
    client, r = login_raw(env)
    body = r.json()
    assert r.status_code == 200
    assert body["user"]["username"] == "ana" and body["user"]["role"] == "operator"
    assert "licenses:write" in body["permissions"] and "users:manage" not in body["permissions"]
    assert len(body["csrf_token"]) >= 40
    assert "argon2" not in r.text and "password_hash" not in r.text
    me = client.get("/api/admin/auth/me")
    assert me.status_code == 200 and me.json()["csrf_token"] == body["csrf_token"]


def test_session_cookie_is_hardened(env):
    env.make_user("ana")
    env.monkeypatch.setenv("LICENSE_COOKIE_SECURE", "true")
    r = env.new_http().post("/api/admin/auth/login", json={"username": "ana", "password": PASSWORD})
    cookie = r.headers["set-cookie"]
    assert cookie.startswith("__Host-lic_session=")
    for flag in ("HttpOnly", "Secure", "Path=/"):
        assert flag in cookie
    assert "samesite=strict" in cookie.lower() and "domain" not in cookie.lower()
    assert "max-age" not in cookie.lower()          # cookie de sesión: no sobrevive al navegador
    assert r.headers["strict-transport-security"].startswith("max-age=")


def test_session_token_is_stored_hashed(env):
    env.make_user("ana")
    panel = env.login()
    with env.db() as db:
        ids = list(db.scalars(select(AdminSession.id)))
    assert ids == [hashlib.sha256(panel.token.encode()).hexdigest()]
    assert panel.token not in ids


def test_wrong_password_and_unknown_user_look_identical(env):
    env.make_user("ana")
    _, bad_pw = login_raw(env, password="incorrecta-incorrecta")
    _, no_user = login_raw(env, username="fantasma")
    assert bad_pw.status_code == no_user.status_code == 401
    assert bad_pw.json() == no_user.json()
    assert bad_pw.json()["error"]["code"] == "invalid_credentials"
    assert COOKIE not in bad_pw.headers.get("set-cookie", "")


def test_username_is_case_insensitive(env):
    env.make_user("ana")
    assert login_raw(env, username="  ANA ")[1].status_code == 200


def test_lockout_after_repeated_failures_then_recovers(env):
    env.make_user("ana")
    for _ in range(5):
        assert login_raw(env, password="mala-mala-mala-1")[1].status_code == 401
    # bloqueada: ni siquiera la contraseña correcta entra
    r = login_raw(env)[1]
    assert r.status_code == 401 and r.json()["error"]["message"].startswith("Usuario o contraseña")
    env.clock.advance(minutes=16)
    assert login_raw(env)[1].status_code == 200
    with env.db() as db:
        events = list(db.scalars(select(AuditLog.event)))
    assert "admin_login_blocked" in events and events.count("admin_login_failed") == 5


def test_successful_login_resets_failure_counter(env):
    env.make_user("ana")
    for _ in range(4):
        login_raw(env, password="mala-mala-mala-1")
    assert login_raw(env)[1].status_code == 200
    for _ in range(4):                                  # otra vez 4: no se acumulan con las viejas
        login_raw(env, password="mala-mala-mala-1")
    assert login_raw(env)[1].status_code == 200


def test_disabled_user_cannot_login_and_sessions_die(env):
    ana_id = env.make_user("ana").id
    env.make_user("root", "admin")
    ana = env.login("ana")
    admin = env.login("root")
    assert admin.patch(f"/api/admin/users/{ana_id}", json={"is_active": False}).status_code == 200
    assert ana.get("/api/admin/auth/me").status_code == 401     # su sesión se cerró
    assert login_raw(env)[1].status_code == 401


def test_login_rate_limit(env):
    env.monkeypatch.setenv("LICENSE_LOGIN_RATE_LIMIT", "3")
    env.make_user("ana")
    codes = [login_raw(env, password="mala-mala-mala-1")[1].status_code for _ in range(5)]
    assert codes == [401, 401, 401, 429, 429]


def test_each_login_creates_a_new_session_token(env):
    env.make_user("ana")
    a, b = env.login(), env.login()
    assert a.token != b.token and a.csrf != b.csrf


# ------------------------------------------------------------------ sin sesión

def test_api_requires_session(env):
    anon = env.new_http()
    for method, url in [("get", "/api/admin/licenses"), ("get", "/api/admin/stats"),
                        ("get", "/api/admin/users"), ("get", "/api/admin/audit"),
                        ("get", "/api/admin/auth/me"), ("post", "/api/admin/licenses"),
                        ("post", "/api/admin/auth/logout")]:
        r = getattr(anon, method)(url)
        assert r.status_code == 401, url
        assert r.json()["error"]["code"] == "unauthenticated"


def test_forged_or_garbage_cookie_is_rejected(env):
    env.make_user("ana")
    for value in ("abc", "x" * 500, hashlib.sha256(b"x").hexdigest()):
        client = env.new_http()
        client.cookies.set(COOKIE, value)
        assert client.get("/api/admin/auth/me").status_code == 401


def test_html_pages_redirect_to_login_with_next(env):
    anon = env.new_http()
    r = anon.get("/admin/licenses?status=grace")
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/login?next=/admin/licenses%3Fstatus%3Dgrace"


# ------------------------------------------------------------------ expiración

def test_idle_timeout(env):
    env.make_user("ana")
    panel = env.login()
    env.clock.advance(minutes=59)
    assert panel.get("/api/admin/auth/me").status_code == 200   # la actividad renueva el plazo
    env.clock.advance(minutes=59)
    assert panel.get("/api/admin/auth/me").status_code == 200
    env.clock.advance(minutes=61)
    assert panel.get("/api/admin/auth/me").status_code == 401


def test_absolute_session_lifetime(env):
    env.make_user("ana")
    panel = env.login()
    for _ in range(12):                                         # actividad constante durante 12 h
        env.clock.advance(minutes=59)
        assert panel.get("/api/admin/auth/me").status_code == 200
    env.clock.advance(minutes=30)                               # pasa de las 12 h
    assert panel.get("/api/admin/auth/me").status_code == 401


def test_logout_invalidates_the_token_server_side(env):
    env.make_user("ana")
    panel = env.login()
    stolen = env.new_http()
    stolen.cookies.set(COOKIE, panel.token)
    assert stolen.get("/api/admin/auth/me").status_code == 200
    assert panel.post("/api/admin/auth/logout").status_code == 200
    assert stolen.get("/api/admin/auth/me").status_code == 401  # la cookie copiada ya no sirve


# ------------------------------------------------------------------ CSRF

def test_csrf_required_on_state_changing_requests(env):
    env.make_user("ana")
    panel = env.login()
    body = {"product": "p", "customer": "c", "plan": "perpetual"}
    no_header = panel.http.post("/api/admin/licenses", json=body)
    wrong = panel.http.post("/api/admin/licenses", json=body, headers={"X-CSRF-Token": "x" * 43})
    ok = panel.post("/api/admin/licenses", json=body)
    assert (no_header.status_code, wrong.status_code, ok.status_code) == (403, 403, 201)
    assert no_header.json()["error"]["code"] == "csrf"


def test_csrf_token_from_another_session_is_rejected(env):
    env.make_user("ana")
    a, b = env.login(), env.login()
    r = a.http.post("/api/admin/licenses", json={"product": "p", "customer": "c",
                                                 "plan": "perpetual"},
                    headers={"X-CSRF-Token": b.csrf})
    assert r.status_code == 403


def test_cross_origin_requests_are_rejected_even_with_valid_token(env):
    env.make_user("ana")
    panel = env.login()
    body = {"product": "p", "customer": "c", "plan": "perpetual"}
    evil = panel.post("/api/admin/licenses", json=body, headers={"Origin": "https://evil.example"})
    null = panel.post("/api/admin/licenses", json=body, headers={"Origin": "null"})
    same = panel.post("/api/admin/licenses", json=body, headers={"Origin": "http://testserver"})
    assert (evil.status_code, null.status_code, same.status_code) == (403, 403, 201)


def test_csrf_not_required_for_reads(env):
    env.make_user("ana")
    panel = env.login()
    assert panel.http.get("/api/admin/licenses").status_code == 200


def test_login_rejects_cross_origin(env):
    env.make_user("ana")
    r = env.new_http().post("/api/admin/auth/login", json={"username": "ana", "password": PASSWORD},
                            headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


# ------------------------------------------------------------------ autorización por rol

MATRIX = [
    # método, url, cuerpo, ¿viewer?, ¿operator?, ¿admin?
    ("get", "/api/admin/stats", None, 200, 200, 200),
    ("get", "/api/admin/licenses", None, 200, 200, 200),
    ("get", "/api/admin/audit", None, 200, 200, 200),
    ("post", "/api/admin/licenses", {"product": "p", "customer": "c", "plan": "perpetual"},
     403, 201, 201),
    ("get", "/api/admin/users", None, 403, 403, 200),
    ("post", "/api/admin/users", {"username": "nuevo_x", "role": "viewer"}, 403, 403, 201),
]


@pytest.mark.parametrize("method,url,body,viewer,operator,admin", MATRIX)
def test_role_matrix(env, method, url, body, viewer, operator, admin):
    for role, expected in (("viewer", viewer), ("operator", operator), ("admin", admin)):
        panel = env.user_with(role, f"{role}_u")
        kwargs = {"json": body} if body else {}
        r = getattr(panel, method)(url, **kwargs)
        assert r.status_code == expected, f"{role} {method} {url}: {r.status_code} {r.text}"
        if expected == 403:
            assert r.json()["error"]["code"] == "forbidden"


def test_viewer_cannot_modify_an_existing_license(env):
    lic_id, _ = env.new_license()
    viewer = env.user_with("viewer")
    for method, url, kw in [("post", f"/api/admin/licenses/{lic_id}/revoke", {}),
                            ("post", f"/api/admin/licenses/{lic_id}/extend", {"json": {"days": 5}}),
                            ("patch", f"/api/admin/licenses/{lic_id}", {"json": {"notes": "x"}}),
                            ("delete", f"/api/admin/licenses/{lic_id}/activations", {})]:
        assert getattr(viewer, method)(url, **kw).status_code == 403, url
    assert viewer.get(f"/api/admin/licenses/{lic_id}").json()["revoked"] is False


def test_role_change_applies_on_next_request(env):
    env.make_user("root", "admin")
    ana = env.user_with("operator", "ana")
    admin = env.login("root")
    assert ana.get("/api/admin/stats").status_code == 200
    with env.db() as db:
        ana_id = db.scalar(select(AdminSession.user_id).limit(1))
    ids = {u["username"]: u["id"] for u in admin.get("/api/admin/users").json()}
    assert admin.patch(f"/api/admin/users/{ids['ana']}", json={"role": "viewer"}).status_code == 200
    assert ana.post("/api/admin/licenses", json={"product": "p", "customer": "c",
                                                 "plan": "perpetual"}).status_code == 403
    assert ana_id is not None


# ------------------------------------------------------------------ contraseñas

def test_change_password_closes_other_sessions_only(env):
    env.make_user("ana")
    a, b = env.login(), env.login()
    new = "otra-contraseña-larga"
    r = a.post("/api/admin/auth/password", json={"current": PASSWORD, "new": new})
    assert r.status_code == 200
    assert a.get("/api/admin/auth/me").status_code == 200       # la actual sigue abierta
    assert b.get("/api/admin/auth/me").status_code == 401       # las demás se cerraron
    assert login_raw(env, password=PASSWORD)[1].status_code == 401
    assert login_raw(env, password=new)[1].status_code == 200


@pytest.mark.parametrize("current,new,fragment", [
    ("incorrecta-incorrecta", "otra-contraseña-larga", "actual no es correcta"),
    (PASSWORD, PASSWORD, "distinta"),
    (PASSWORD, "corta", "al menos 12"),
    (PASSWORD, "ana-secreta-larga-9", "contiene el usuario"),
])
def test_change_password_validation(env, current, new, fragment):
    env.make_user("ana")
    r = env.login().post("/api/admin/auth/password", json={"current": current, "new": new})
    assert r.status_code == 422 and fragment in r.json()["error"]["message"]


def test_must_change_password_blocks_everything_else(env):
    env.make_user("nuevo_u", "admin", must_change=True)
    panel = env.login("nuevo_u")
    r = panel.get("/api/admin/licenses")
    assert r.status_code == 403 and r.json()["error"]["code"] == "password_change_required"
    assert panel.get("/api/admin/auth/me").json()["user"]["must_change_password"] is True
    page = panel.get("/admin/licenses")
    assert page.status_code == 303 and page.headers["location"] == "/admin/account"

    ok = panel.post("/api/admin/auth/password", json={"current": PASSWORD,
                                                      "new": "contraseña-nueva-segura"})
    assert ok.status_code == 200
    assert panel.get("/api/admin/licenses").status_code == 200


def test_admin_reset_password_forces_change_and_kills_sessions(env):
    env.make_user("root", "admin")
    victim = env.user_with("operator", "ana")
    admin = env.login("root")
    uid = {u["username"]: u["id"] for u in admin.get("/api/admin/users").json()}["ana"]

    r = admin.post(f"/api/admin/users/{uid}/reset-password", json={})
    temp = r.json()["temporary_password"]
    assert r.status_code == 200 and len(temp) >= 12
    assert victim.get("/api/admin/auth/me").status_code == 401
    panel = env.login("ana", temp)
    assert panel.get("/api/admin/auth/me").json()["user"]["must_change_password"] is True
    assert login_raw(env, password=PASSWORD)[1].status_code == 401


def test_cannot_demote_disable_or_edit_yourself_and_last_admin_is_protected(env):
    env.make_user("root", "admin")
    root = env.login("root")
    me = root.get("/api/admin/auth/me").json()["user"]["id"]
    for payload in ({"role": "viewer"}, {"is_active": False}):
        r = root.patch(f"/api/admin/users/{me}", json=payload)
        assert r.status_code == 403
    assert root.post(f"/api/admin/users/{me}/reset-password", json={}).status_code == 403

    # con un segundo admin, ya se puede degradar al primero... pero no al último
    env.make_user("otro", "admin")
    other = env.login("otro")
    ids = {u["username"]: u["id"] for u in other.get("/api/admin/users").json()}
    assert other.patch(f"/api/admin/users/{ids['root']}", json={"role": "viewer"}).status_code == 200
    r = root.patch(f"/api/admin/users/{ids['otro']}", json={"role": "viewer"})
    assert r.status_code in (401, 403)   # root ya no es admin: no puede tocar a nadie

    with env.db() as db:
        from app.services import users as svc
        with pytest.raises(ValueError, match="al menos un administrador"):
            svc.set_role(db, ids["otro"], "viewer")
        with pytest.raises(ValueError, match="al menos un administrador"):
            svc.set_active(db, ids["otro"], False)


def test_user_management_validation(env):
    env.make_user("root", "admin")
    root = env.login("root")
    assert root.post("/api/admin/users", json={"username": "ab", "role": "viewer"}).status_code == 422
    assert root.post("/api/admin/users", json={"username": "ok_user", "role": "dios"}).status_code == 422
    assert root.post("/api/admin/users", json={"username": "ok_user", "role": "viewer",
                                               "password": "corta"}).status_code == 422
    first = root.post("/api/admin/users", json={"username": "ok_user", "role": "viewer"})
    assert first.status_code == 201 and first.json()["temporary_password"]
    dup = root.post("/api/admin/users", json={"username": "OK_USER", "role": "viewer"})
    assert dup.status_code == 422 and "ya existe" in dup.json()["error"]["message"]
    assert root.patch("/api/admin/users/9999", json={"role": "viewer"}).status_code == 404


def test_users_list_never_exposes_hashes(env):
    env.make_user("root", "admin")
    text = env.login("root").get("/api/admin/users").text
    assert "argon2" not in text and "password_hash" not in text


def test_security_headers_on_admin_responses(env):
    env.make_user("ana")
    r = env.login().get("/api/admin/auth/me")
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-frame-options"] == "DENY" and r.headers["x-content-type-options"] == "nosniff"
    page = env.new_http().get("/admin/login")
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
    assert "script-src 'self'" in page.headers["content-security-policy"]
