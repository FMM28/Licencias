"""Panel web (HTML): redirecciones, páginas por rol, CSRF, escape de HTML y clave de un solo uso."""
import re

import pytest

from tests.conftest import COOKIE, PASSWORD

PAGES = ["/admin", "/admin/licenses", "/admin/licenses/new", "/admin/audit", "/admin/account"]


def form_login(env, username="ana", password=PASSWORD, client=None, **extra):
    client = client or env.new_http()
    r = client.post("/admin/login", data={"username": username, "password": password, **extra})
    return client, r


def csrf_of(client, url="/admin/account"):
    html = client.get(url).text
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


def test_anonymous_is_redirected_to_login_with_next(env):
    r = env.http.get("/admin/licenses?q=x")
    assert r.status_code == 303 and r.headers["location"].startswith("/admin/login?next=")


def test_login_page_renders(env):
    r = env.http.get("/admin/login")
    assert r.status_code == 200 and "<form" in r.text


def test_form_login_flow_and_logout(env):
    env.make_user("ana", "admin")
    client, r = form_login(env)
    assert r.status_code == 303 and COOKIE in client.cookies
    assert client.get("/admin").status_code == 200
    token = csrf_of(client)
    out = client.post("/admin/logout", data={"csrf_token": token})
    assert out.status_code == 303
    assert client.get("/admin").status_code == 303


def test_bad_login_is_generic(env):
    env.make_user("ana")
    _, bad = form_login(env, password="incorrecta-incorrecta")
    _, ghost = form_login(env, username="fantasma")
    assert bad.status_code == ghost.status_code == 401 or bad.status_code == ghost.status_code == 200
    assert bad.status_code == ghost.status_code


@pytest.mark.parametrize("role", ["viewer", "operator", "admin"])
def test_every_page_renders_for_each_role(env, role):
    lic_id, _ = env.new_license(customer="Cliente <b>uno</b>")
    panel = env.user_with(role)
    for url in PAGES + [f"/admin/licenses/{lic_id}"]:
        r = panel.get(url)
        want = 403 if url == "/admin/licenses/new" and role == "viewer" else 200
        assert r.status_code == want, (url, r.status_code)
        assert "<b>uno</b>" not in r.text          # el nombre del cliente se escapa
    assert (panel.get("/admin/users").status_code == 200) == (role == "admin")


def test_viewer_cannot_create(env):
    panel = env.user_with("viewer")
    assert panel.get("/admin/licenses/new").status_code == 403
    r = panel.form("/admin/licenses", {"customer": "X", "product": "mi-app", "plan": "perpetual"})
    assert r.status_code == 403


def test_create_license_shows_key_once(env):
    panel = env.user_with("operator")
    r = panel.form("/admin/licenses", {"customer": "Nueva SA", "product": "mi-app",
                                       "plan": "subscription", "days": "30", "max_activations": "2"})
    assert r.status_code == 303
    page = panel.get(r.headers["location"])
    keys = re.findall(r"data-key>([^<]+)<", page.text)
    assert len(keys) == 1 and keys[0].strip()
    again = panel.get(r.headers["location"])
    assert keys[0] not in again.text


def test_form_post_without_csrf_is_rejected(env):
    env.make_user("ana")
    client, _ = form_login(env)
    r = client.post("/admin/licenses", data={"customer": "X", "product": "mi-app", "plan": "perpetual"})
    assert r.status_code == 403


def test_cross_origin_post_is_rejected(env):
    env.make_user("ana")
    client, _ = form_login(env)
    token = csrf_of(client)
    r = client.post("/admin/licenses", data={"csrf_token": token, "customer": "X",
                                             "product": "mi-app", "plan": "perpetual"},
                    headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_search_treats_wildcards_literally(env):
    env.new_license(customer="100% Real")
    env.new_license(customer="Otro")
    panel = env.user_with("viewer")
    html = panel.get("/admin/licenses", params={"q": "%"}).text
    assert "100% Real" in html and "Otro" not in html
    html = panel.get("/admin/licenses", params={"q": "00_"}).text   # «_» no es comodín
    assert "100% Real" not in html


def test_pagination_links(env):
    for i in range(30):
        env.new_license(customer=f"Cliente {i:02d}")
    panel = env.user_with("viewer")
    assert "page=2" in panel.get("/admin/licenses").text
    assert panel.get("/admin/licenses", params={"page": 2}).status_code == 200


def test_security_headers_and_csp(env):
    panel = env.user_with("viewer")
    r = panel.get("/admin")
    assert r.headers["cache-control"].startswith("no-store")
    assert r.headers["x-frame-options"] == "DENY"
    csp = r.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "unsafe-inline" not in csp.split("script-src")[1].split(";")[0]
    assert "style=" not in r.text and "onclick" not in r.text and "<script>" not in r.text


def test_forced_password_change_redirects(env):
    env.make_user("temp", "admin", must_change=True)
    client, _ = form_login(env, username="temp")
    r = client.get("/admin/licenses")
    assert r.status_code == 303 and r.headers["location"].endswith("/admin/account")
    assert client.get("/admin/account").status_code == 200


def test_unknown_page_uses_styled_error(env):
    panel = env.user_with("viewer")
    r = panel.get("/admin/licenses/lic_noexiste")
    assert r.status_code == 404 and "<html" in r.text
