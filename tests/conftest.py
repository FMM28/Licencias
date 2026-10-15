"""Fixtures compartidas.

Las pruebas corren contra un MariaDB de pruebas (`make db-up` lo levanta con Docker, o usa
uno propio). Variables obligatorias:

    TEST_DATABASE_URL="mariadb+pymysql://lic:clave@127.0.0.1/licenses_test"
    TEST_MIGRATIONS_DATABASE_URL="mariadb+pymysql://lic:clave@127.0.0.1/licenses_mig_test"

Las bases deben existir y NO deben ser las de producción: se vacían en cada prueba. La de
migraciones es distinta porque esas pruebas suben y bajan el esquema entero.
"""
import os

os.environ["LICENSE_SKIP_DOTENV"] = "1"  # las pruebas no deben leer el .env de desarrollo
import time
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app import models  # noqa: F401  (registra las tablas)
from app.core import crypto, ratelimit, timeutil
from app.db import migrate
from app.db import session as dbsession
from app.db.base import Base
from app.main import app
from app.services import licenses as license_service
from app.services import users as user_service
from sdk.licensing_client import LicenseClient

PRODUCT = "mi-app"
PASSWORD = "correct-horse-battery"
COOKIE = "lic_session"  # nombre sin prefijo __Host- (las pruebas corren por http)


class Clock:
    """Reloj falso compartido por servidor y SDK."""

    def __init__(self):
        self.offset = 0.0

    def ts(self) -> float:
        return time.time() + self.offset

    def now(self) -> datetime:
        return datetime.fromtimestamp(self.ts(), timezone.utc)

    def advance(self, days: float = 0.0, minutes: float = 0.0) -> None:
        self.offset += days * 86400 + minutes * 60


class DeadHTTP:
    """Simula que no hay internet."""

    def post(self, *a, **k):
        raise ConnectionError("sin red")


class Panel:
    """Cliente HTTP con sesión iniciada: añade solo el token CSRF a cada petición."""

    def __init__(self, http: TestClient, csrf: str, token: str):
        self.http, self.csrf, self.token = http, csrf, token

    def _kw(self, kw):
        headers = dict(kw.pop("headers", {}))
        headers.setdefault("X-CSRF-Token", self.csrf)
        return {**kw, "headers": headers}

    def get(self, url, **kw):
        return self.http.get(url, **kw)

    def post(self, url, **kw):
        return self.http.post(url, **self._kw(kw))

    def patch(self, url, **kw):
        return self.http.patch(url, **self._kw(kw))

    def delete(self, url, **kw):
        return self.http.delete(url, **self._kw(kw))

    def form(self, url, data=None, **kw):
        """POST de formulario HTML (el token CSRF va como campo oculto)."""
        return self.http.post(url, data={**(data or {}), "csrf_token": self.csrf}, **kw)


def _wipe(url: str) -> None:
    engine = create_engine(dbsession.normalize_url(url))
    with engine.begin() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())
        conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))
    engine.dispose()


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        pytest.exit(f"Falta {name}. Las pruebas necesitan un MariaDB de pruebas: "
                    "corre `make db-up` y `make test` (ver README).", returncode=2)
    return value


@pytest.fixture(scope="session")
def _db_url():
    url = require_env("TEST_DATABASE_URL")
    migrate.downgrade(url, "base")  # arranca desde cero
    migrate.upgrade(url)
    return url


@pytest.fixture
def db_url(_db_url):
    _wipe(_db_url)
    return _db_url


@pytest.fixture
def env(db_url, tmp_path, monkeypatch):
    priv, pub = crypto.generate_keypair()
    for key, value in {
        "LICENSE_DB_URL": db_url, "LICENSE_PRIVATE_KEY": priv, "LICENSE_RATE_LIMIT": "1000",
        "LICENSE_TOKEN_TTL_DAYS": "7", "LICENSE_EXPIRY_GRACE_DAYS": "3",
        "LICENSE_COOKIE_SECURE": "false", "LICENSE_LOGIN_RATE_LIMIT": "1000",
        "LICENSE_SESSION_IDLE_MINUTES": "60", "LICENSE_SESSION_MAX_HOURS": "12",
        "LICENSE_LOGIN_MAX_FAILURES": "5", "LICENSE_LOGIN_LOCK_MINUTES": "15",
        "LICENSE_AUTO_MIGRATE": "false",
    }.items():
        monkeypatch.setenv(key, value)
    dbsession.configure(db_url)
    ratelimit.reset_all()
    clock = Clock()
    timeutil.set_clock(clock.now)

    def http() -> TestClient:
        return TestClient(app, follow_redirects=False)

    http_main = http()

    def sdk(name="a", fp=None, product=PRODUCT) -> LicenseClient:
        c = LicenseClient("http://testserver", product, pub,
                          storage_path=str(tmp_path / f"{name}.json"),
                          http=http_main, clock=clock.ts)
        if fp:
            c.fingerprint = lambda: fp
        return c

    def new_license(**kw):
        kw.setdefault("product", PRODUCT)
        kw.setdefault("customer", "ACME")
        kw.setdefault("plan", "subscription")
        kw.setdefault("days", 365)
        kw.setdefault("features", ["export"])
        with dbsession.new_session() as db:
            lic, key = license_service.create_license(db, **kw)
        return lic.id, key

    def make_user(username="ana", role="admin", password=PASSWORD, must_change=False):
        with dbsession.new_session() as db:
            return user_service.create_user(db, username=username, password=password,
                                            role=role, must_change=must_change)

    def login(username="ana", password=PASSWORD) -> Panel:
        client = http()
        r = client.post("/api/admin/auth/login", json={"username": username,
                                                       "password": password})
        assert r.status_code == 200, r.text
        return Panel(client, r.json()["csrf_token"], client.cookies.get(COOKIE))

    def user_with(role, username=None) -> Panel:
        username = username or f"{role}_user"
        make_user(username, role)
        return login(username)

    yield SimpleNamespace(
        http=http_main, new_http=http, sdk=sdk, new_license=new_license, make_user=make_user,
        login=login, user_with=user_with, clock=clock, pub=pub, db=dbsession.new_session,
        monkeypatch=monkeypatch)
    timeutil.reset_clock()
    ratelimit.reset_all()
