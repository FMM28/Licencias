"""Mensajes de un solo uso para la página siguiente (patrón Post/Redirect/Get).

Se guardan en la fila de la sesión. Los secretos (por ejemplo la clave de una licencia recién
creada, o una contraseña temporal) se cifran con una clave derivada del token de la cookie:
en la base de datos solo queda texto cifrado que ni siquiera el servidor puede leer sin
la cookie del administrador, y se borra en cuanto se muestra."""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from app.models import AdminSession


def _fernet(cookie_token: str) -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(b"flash:" + cookie_token.encode()).digest())
    return Fernet(key)


def push(db: Session, session: AdminSession, cookie_token: str, kind: str, text: str,
         secret: str | None = None, secret_label: str | None = None) -> None:
    """kind: success | error | info | secret"""
    item = {"kind": kind, "text": text}
    if secret is not None:
        item["secret"] = _fernet(cookie_token).encrypt(secret.encode()).decode()
        item["secret_label"] = secret_label or ""
    session.flash = [*(session.flash or []), item]  # reasignar: SQLAlchemy no ve mutaciones en JSON
    db.commit()


def pop(db: Session, session: AdminSession, cookie_token: str) -> list[dict]:
    items = session.flash or []
    if not items:
        return []
    out = []
    for item in items:
        shown = {"kind": item["kind"], "text": item["text"],
                 "secret": None, "secret_label": item.get("secret_label", "")}
        if item.get("secret"):
            try:
                shown["secret"] = _fernet(cookie_token).decrypt(item["secret"].encode()).decode()
            except InvalidToken:
                shown["secret"] = None
        out.append(shown)
    session.flash = None
    db.commit()
    return out
