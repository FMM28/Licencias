"""Migraciones Alembic: subir, bajar, repetir y comprobar que coinciden con los modelos.
Usa TEST_MIGRATIONS_DATABASE_URL: una base de MariaDB aparte y vacía, porque estas pruebas
suben y bajan el esquema completo."""

import pytest
from sqlalchemy import create_engine, inspect, text

from app.db import migrate
from app.db.session import normalize_url
from tests.conftest import require_env

EXPECTED_TABLES = {"licenses", "activations", "audit_log", "admin_users", "admin_sessions"}


@pytest.fixture
def url():
    external = require_env("TEST_MIGRATIONS_DATABASE_URL")
    migrate.downgrade(external, "base")
    yield external
    migrate.downgrade(external, "base")


def tables(url):
    engine = create_engine(normalize_url(url))
    try:
        return set(inspect(engine).get_table_names()) - {"alembic_version"}
    finally:
        engine.dispose()


def test_upgrade_creates_everything_and_matches_models(url):
    migrate.upgrade(url)
    assert tables(url) == EXPECTED_TABLES
    assert migrate.current_revision(url) == migrate.head_revision() == "0003"
    migrate.check(url)    # lanza si los modelos tienen cambios sin migración


def test_step_by_step_and_full_downgrade(url):
    migrate.upgrade(url, "0001")
    assert tables(url) == {"licenses", "activations", "audit_log"}
    migrate.upgrade(url)
    migrate.downgrade(url, "0001")
    assert tables(url) == {"licenses", "activations", "audit_log"}
    migrate.downgrade(url, "base")
    assert tables(url) == set() and migrate.current_revision(url) is None
    migrate.upgrade(url)                                 # y se puede volver a subir
    assert tables(url) == EXPECTED_TABLES


def test_upgrade_is_idempotent(url):
    migrate.upgrade(url)
    migrate.upgrade(url)
    assert migrate.is_up_to_date(url)


def test_data_survives_0002_upgrade(url):
    """Una base con datos de la versión 1 (sin panel) se actualiza sin perder nada."""
    migrate.upgrade(url, "0001")
    engine = create_engine(normalize_url(url))
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO licenses (id, key_hash, product, customer, plan, features, "
            "max_activations, revoked, created_at) VALUES ('lic_old', 'h', 'p', 'Cliente viejo', "
            "'perpetual', '[]', 1, 0, '2026-01-01 00:00:00')"))
        conn.execute(text("INSERT INTO audit_log (ts, license_id, event) "
                          "VALUES ('2026-01-01 00:00:00', 'lic_old', 'license_created')"))
    migrate.upgrade(url)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT customer FROM licenses")).scalar() == "Cliente viejo"
        assert conn.execute(text("SELECT actor FROM audit_log")).scalar() is None
    engine.dispose()


def test_0003_marks_existing_active_installs_as_confirmed(url):
    migrate.upgrade(url, "0002")
    engine = create_engine(normalize_url(url))
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO licenses (id, key_hash, product, customer, plan, features, "
            "max_activations, revoked, created_at) VALUES ('lic_old', 'h', 'p', 'C', "
            "'perpetual', '[]', 2, 0, '2026-01-01 00:00:00')"))
        for fp, active in (("a", 1), ("b", 0)):
            conn.execute(text(
                "INSERT INTO activations (license_id, fingerprint, active, created_at, last_seen) "
                f"VALUES ('lic_old', '{fp}', {active}, '2026-01-02 00:00:00', '2026-01-03 00:00:00')"))
    migrate.upgrade(url)
    with engine.connect() as conn:
        rows = dict(conn.execute(text("SELECT fingerprint, confirmed_at FROM activations")).all())
    engine.dispose()
    assert rows["a"] is not None and rows["b"] is None


def test_tables_are_innodb_utf8mb4_regardless_of_server_defaults(url):
    """Las opciones de tabla deben aplicarse explícitamente (no heredarse del servidor).
    Para que la prueba demuestre algo, crea la base de pruebas con otro charset por defecto:
        CREATE DATABASE licenses_mig_test CHARACTER SET latin1;"""
    migrate.upgrade(url)
    engine = create_engine(normalize_url(url))
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT table_name, engine, table_collation FROM information_schema.tables "
            "WHERE table_schema = DATABASE() AND table_name <> 'alembic_version'")).all()
    engine.dispose()
    assert {r[0] for r in rows} == EXPECTED_TABLES
    assert {(r[1], r[2]) for r in rows} == {("InnoDB", "utf8mb4_unicode_ci")}


def test_offline_sql_generation_for_mariadb(tmp_path):
    """`alembic upgrade head --sql` sirve para revisar el DDL antes de aplicarlo en producción."""
    import io

    from alembic import command
    cfg = migrate.alembic_config("mariadb+pymysql://u:p@localhost/x")
    buf = io.StringIO()
    cfg.output_buffer = buf
    command.upgrade(cfg, "head", sql=True)
    sql = buf.getvalue()
    assert "CREATE TABLE admin_users" in sql and "ENGINE=InnoDB" in sql
    assert "utf8mb4" in sql and "INSERT INTO alembic_version" in sql
