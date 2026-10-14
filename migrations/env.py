from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from app import models  # noqa: F401  (registra las tablas)
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import normalize_url

config = context.config
if config.config_file_name:  # solo al usar el comando `alembic` (no al llamarlo desde código)
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url() -> str:
    return config.attributes.get("url") or normalize_url(get_settings().db_url)


def run_migrations_offline() -> None:
    """Modo --sql: genera el script sin conectarse a la base de datos."""
    context.configure(
        url=get_url(), target_metadata=target_metadata, literal_binds=True,
        dialect_opts={"paramstyle": "named"}, compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(get_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
