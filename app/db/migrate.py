"""Utilidades para ejecutar Alembic desde código (CLI, arranque del servidor y pruebas)."""
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine

from app.core.config import get_settings
from app.db.session import normalize_url

ROOT = Path(__file__).resolve().parents[2]  # raíz del proyecto (donde vive migrations/)


def alembic_config(url: str | None = None) -> Config:
    # Config() sin archivo .ini: así Alembic no reconfigura el logging de uvicorn.
    cfg = Config()
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    cfg.attributes["url"] = normalize_url(url or get_settings().db_url)
    return cfg


def _scripts() -> ScriptDirectory:
    """Lee las migraciones del disco; no necesita conexión ni URL."""
    cfg = Config()
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    return ScriptDirectory.from_config(cfg)


def upgrade(url: str | None = None, revision: str = "head") -> None:
    command.upgrade(alembic_config(url), revision)


def downgrade(url: str | None = None, revision: str = "-1") -> None:
    command.downgrade(alembic_config(url), revision)


def stamp(url: str | None = None, revision: str = "head") -> None:
    command.stamp(alembic_config(url), revision)


def check(url: str | None = None) -> None:
    """Lanza error si los modelos tienen cambios que no están en ninguna migración."""
    command.check(alembic_config(url))


def head_revision() -> str | None:
    return _scripts().get_current_head()


def current_revision(url: str | None = None) -> str | None:
    engine = create_engine(normalize_url(url or get_settings().db_url))
    try:
        with engine.connect() as conn:
            return MigrationContext.configure(conn).get_current_revision()
    finally:
        engine.dispose()


def is_up_to_date(url: str | None = None) -> bool:
    return current_revision(url) == head_revision()
