"""Configuración del servicio. Todo se lee de variables de entorno en cada llamada,
así es fácil cambiarla en pruebas y no hay estado global oculto.
"""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Localiza la raíz del proyecto independientemente del directorio de ejecución.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"

# No sobrescribe las variables que ya estén definidas en el entorno.
load_dotenv(ENV_FILE, override=False)


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    # Base de datos
    db_url: str
    auto_migrate: bool

    # Firma de licencias
    private_key_file: str
    private_key_b64: str | None
    token_ttl_days: int
    expiry_grace_days: int
    rate_limit_per_min: int

    # Panel de administración
    cookie_secure: bool
    session_idle_minutes: int
    session_max_hours: int
    login_max_failures: int
    login_lock_minutes: int
    login_rate_limit_per_min: int

    # Varios
    docs_enabled: bool


def get_settings() -> Settings:
    return Settings(
        db_url=os.getenv("LICENSE_DB_URL", ""),
        auto_migrate=_bool("LICENSE_AUTO_MIGRATE", False),
        private_key_file=os.getenv(
            "LICENSE_PRIVATE_KEY_FILE",
            str(PROJECT_ROOT / "keys" / "private.key"),
        ),
        private_key_b64=os.getenv("LICENSE_PRIVATE_KEY"),
        token_ttl_days=int(os.getenv("LICENSE_TOKEN_TTL_DAYS", "7")),
        expiry_grace_days=int(os.getenv("LICENSE_EXPIRY_GRACE_DAYS", "3")),
        rate_limit_per_min=int(os.getenv("LICENSE_RATE_LIMIT", "30")),
        cookie_secure=_bool("LICENSE_COOKIE_SECURE", True),
        session_idle_minutes=int(
            os.getenv("LICENSE_SESSION_IDLE_MINUTES", "60")
        ),
        session_max_hours=int(
            os.getenv("LICENSE_SESSION_MAX_HOURS", "12")
        ),
        login_max_failures=int(
            os.getenv("LICENSE_LOGIN_MAX_FAILURES", "5")
        ),
        login_lock_minutes=int(
            os.getenv("LICENSE_LOGIN_LOCK_MINUTES", "15")
        ),
        login_rate_limit_per_min=int(
            os.getenv("LICENSE_LOGIN_RATE_LIMIT", "10")
        ),
        docs_enabled=_bool("LICENSE_ENABLE_DOCS", False),
    )
