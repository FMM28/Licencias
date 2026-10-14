from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

_engine: Engine | None = None
_session_factory: sessionmaker | None = None


def normalize_url(url: str) -> str:
    """Acepta `mariadb://` o `mysql://` a secas y los convierte al driver PyMySQL;
    para MariaDB/MySQL fuerza utf8mb4 (emojis y acentos sin sorpresas)."""
    if not (url or "").strip():
        raise ValueError("Falta LICENSE_DB_URL (ej. mariadb+pymysql://usuario:clave@host/licenses)")
    u = make_url(url)
    if u.get_backend_name() not in ("mysql", "mariadb"):
        raise ValueError(
            f"LICENSE_DB_URL debe apuntar a MariaDB (mariadb+pymysql://usuario:clave@host/base); "
            f"recibí el motor «{u.get_backend_name()}», que no está soportado")
    if u.drivername in ("mysql", "mariadb"):
        u = u.set(drivername="mariadb+pymysql")
    if "charset" not in u.query:
        u = u.update_query_dict({"charset": "utf8mb4"})
    return u.render_as_string(hide_password=False)


def configure(url: str) -> None:
    """(Re)configura la conexión. NO crea tablas: eso lo hacen las migraciones Alembic."""
    global _engine, _session_factory
    url = normalize_url(url)
    # MariaDB cierra conexiones ociosas (wait_timeout); reciclamos antes de que lo haga.
    kwargs: dict = {"pool_pre_ping": True, "pool_recycle": 280}
    if _engine is not None:
        _engine.dispose()
    _engine = create_engine(url, **kwargs)
    _session_factory = sessionmaker(bind=_engine, expire_on_commit=False)
    from app import models  # noqa: F401  (registra las tablas en Base.metadata)


def get_engine() -> Engine:
    if _engine is None:
        configure(get_settings().db_url)
    assert _engine is not None
    return _engine


def session_factory() -> sessionmaker:
    if _session_factory is None:
        configure(get_settings().db_url)
    assert _session_factory is not None
    return _session_factory


def new_session() -> Session:
    return session_factory()()


def get_db():
    """Dependencia de FastAPI: una sesión por petición."""
    db = new_session()
    try:
        yield db
    finally:
        db.close()
