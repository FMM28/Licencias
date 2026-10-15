"""Configuración del servicio. Todo se lee de variables de entorno en cada llamada,
así es fácil cambiarla en pruebas y no hay estado global oculto."""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _load_env_file() -> None:
    """Lee `.env` del directorio actual (o el de LICENSE_ENV_FILE). Las variables que ya estén
    definidas en el entorno tienen prioridad. Se omite con LICENSE_SKIP_DOTENV=1 (pruebas)."""
    if os.getenv("LICENSE_SKIP_DOTENV"):
        return
    path = Path(os.getenv("LICENSE_ENV_FILE") or ".env")
    if path.is_file():
        load_dotenv(path, override=False)


_load_env_file()


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    # --- base de datos
    db_url: str
    auto_migrate: bool
    # --- firma de licencias
    private_key_file: str
    private_key_b64: str | None
    token_ttl_days: int
    expiry_grace_days: int
    rate_limit_per_min: int
    # --- panel de administración
    cookie_secure: bool
    session_idle_minutes: int
    session_max_hours: int
    login_max_failures: int
    login_lock_minutes: int
    login_rate_limit_per_min: int
    # --- varios
    docs_enabled: bool


def get_settings() -> Settings:
    return Settings(
        # MariaDB:  mariadb+pymysql://usuario:clave@host:3306/licenses
        # (el driver y ?charset=utf8mb4 se completan solos). Es obligatoria; si falta,
        # app.db.session avisa con un error claro.
        db_url=os.getenv("LICENSE_DB_URL", ""),
        # Si es true, el servidor aplica las migraciones pendientes al arrancar.
        # Con varias instancias es mejor ejecutar `python -m app.cli db upgrade` una sola vez.
        auto_migrate=_bool("LICENSE_AUTO_MIGRATE", False),
        # La clave privada Ed25519. Puede venir de un archivo o de una variable.
        private_key_file=os.getenv("LICENSE_PRIVATE_KEY_FILE", "keys/private.key"),
        private_key_b64=os.getenv("LICENSE_PRIVATE_KEY"),
        # Cuánto dura cada token firmado. Es también el "periodo de gracia offline":
        # el cliente puede trabajar sin internet hasta que el token expira.
        token_ttl_days=int(os.getenv("LICENSE_TOKEN_TTL_DAYS", "7")),
        # Días extra que se toleran tras vencer una suscripción (cobros manuales).
        expiry_grace_days=int(os.getenv("LICENSE_EXPIRY_GRACE_DAYS", "3")),
        rate_limit_per_min=int(os.getenv("LICENSE_RATE_LIMIT", "30")),
        # Cookie con flag Secure (requiere HTTPS). Pon false SOLO en desarrollo local por http.
        cookie_secure=_bool("LICENSE_COOKIE_SECURE", True),
        session_idle_minutes=int(os.getenv("LICENSE_SESSION_IDLE_MINUTES", "60")),
        session_max_hours=int(os.getenv("LICENSE_SESSION_MAX_HOURS", "12")),
        login_max_failures=int(os.getenv("LICENSE_LOGIN_MAX_FAILURES", "5")),
        login_lock_minutes=int(os.getenv("LICENSE_LOGIN_LOCK_MINUTES", "15")),
        login_rate_limit_per_min=int(os.getenv("LICENSE_LOGIN_RATE_LIMIT", "10")),
        # /docs y /openapi.json (Swagger). Desactivado por defecto.
        docs_enabled=_bool("LICENSE_ENABLE_DOCS", False),
    )
