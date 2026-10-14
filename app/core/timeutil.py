"""Reloj del servicio. Todo el código pide la hora aquí, así las pruebas pueden viajar en el tiempo."""
from datetime import datetime, timezone
from typing import Callable


def _real_now() -> datetime:
    return datetime.now(timezone.utc)


_now: Callable[[], datetime] = _real_now


def set_clock(fn: Callable[[], datetime]) -> None:
    """Solo para pruebas: `fn` debe devolver un datetime con zona horaria."""
    global _now
    _now = fn


def reset_clock() -> None:
    global _now
    _now = _real_now


def utcnow() -> datetime:
    """UTC "naive" y sin microsegundos: MariaDB DATETIME guarda segundos, así lo que se
    calcula en memoria coincide exactamente con lo que se lee de la base de datos."""
    return _now().astimezone(timezone.utc).replace(tzinfo=None, microsecond=0)


def to_ts(dt: datetime | None) -> int | None:
    return None if dt is None else int(dt.replace(tzinfo=timezone.utc).timestamp())
