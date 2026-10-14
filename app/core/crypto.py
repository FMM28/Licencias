"""Firma y verificación de tokens con Ed25519.

Formato del token:  base64url(payload_json) + "." + base64url(firma)
La firma se calcula sobre los bytes del primer segmento tal cual viajan,
así no hay problemas de canonicalización de JSON entre Python, Java, etc.
"""
import base64
import json
from functools import lru_cache

from nacl.exceptions import BadSignatureError
from nacl.signing import SigningKey, VerifyKey

from app.core.config import Settings


def b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def generate_keypair() -> tuple[str, str]:
    """Devuelve (clave_privada_b64, clave_publica_b64)."""
    sk = SigningKey.generate()
    return b64e(bytes(sk)), b64e(bytes(sk.verify_key))


@lru_cache(maxsize=8)
def _load(path: str, b64: str | None) -> SigningKey:
    if b64:
        seed = b64d(b64.strip())
    else:
        with open(path, "r", encoding="utf-8") as fh:
            seed = b64d(fh.read().strip())
    return SigningKey(seed)


def load_signing_key(settings: Settings) -> SigningKey:
    try:
        return _load(settings.private_key_file, settings.private_key_b64)
    except FileNotFoundError as exc:
        raise RuntimeError(
            "No se encontró la clave privada. Ejecuta `python -m app.cli init` "
            "o define LICENSE_PRIVATE_KEY / LICENSE_PRIVATE_KEY_FILE."
        ) from exc


def public_key_b64(settings: Settings) -> str:
    return b64e(bytes(load_signing_key(settings).verify_key))


def sign_token(payload: dict, signing_key: SigningKey) -> str:
    body = b64e(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    signature = signing_key.sign(body.encode()).signature
    return f"{body}.{b64e(signature)}"


def verify_token(token: str, public_key: str) -> dict:
    """Verifica la firma y devuelve el payload. Lanza ValueError si es inválido."""
    try:
        body, sig = token.split(".")
        VerifyKey(b64d(public_key)).verify(body.encode(), b64d(sig))
        return json.loads(b64d(body))
    except (ValueError, BadSignatureError) as exc:
        raise ValueError("firma inválida") from exc
