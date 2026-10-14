"""Contraseñas, tokens de sesión y permisos por rol."""
import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()  # argon2id con los parámetros por defecto de la librería
_DUMMY_HASH = _hasher.hash("contraseña-señuelo-para-igualar-tiempos")

MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 128

# ---------------------------------------------------------------- roles y permisos
# viewer   : solo lectura (licencias, activaciones, bitácora)
# operator : además crea licencias, renueva, revoca, libera activaciones
# admin    : además gestiona usuarios del panel
ROLES = ("viewer", "operator", "admin")
PERMISSIONS: dict[str, frozenset[str]] = {
    "viewer": frozenset({"licenses:read", "audit:read"}),
    "operator": frozenset({"licenses:read", "audit:read", "licenses:write"}),
    "admin": frozenset({"licenses:read", "audit:read", "licenses:write", "users:manage"}),
}
ROLE_LABELS = {"viewer": "Lectura", "operator": "Operador", "admin": "Administrador"}


def permissions_for(role: str) -> frozenset[str]:
    return PERMISSIONS.get(role, frozenset())  # rol desconocido = sin permisos


# ---------------------------------------------------------------- contraseñas

def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def burn_time(password: str) -> None:
    """Gasta el mismo tiempo que una verificación real. Se usa cuando el usuario no existe
    o está bloqueado, para que el tiempo de respuesta no delate qué usuarios existen."""
    verify_password(_DUMMY_HASH, password)


_COMMON = {"password1234", "contraseña123", "123456789012", "qwertyuiop12",
           "administrador", "adminadmin12", "letmein12345", "welcome12345"}


def validate_password(password: str, username: str | None = None) -> None:
    """Política basada en longitud (NIST 800-63B). Lanza ValueError con un mensaje legible."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"La contraseña debe tener al menos {MIN_PASSWORD_LENGTH} caracteres")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise ValueError(f"La contraseña no puede pasar de {MAX_PASSWORD_LENGTH} caracteres")
    low = password.lower()
    if len(set(password)) < 5:
        raise ValueError("La contraseña es demasiado repetitiva")
    if low in _COMMON or (username and username.lower() in low):
        raise ValueError("La contraseña es demasiado predecible (o contiene el usuario)")


def generate_password() -> str:
    """Contraseña temporal legible: 4 bloques de 5 caracteres sin ambiguos."""
    alphabet = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "-".join("".join(secrets.choice(alphabet) for _ in range(5)) for _ in range(4))


# ---------------------------------------------------------------- tokens

def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
