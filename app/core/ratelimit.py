"""Limitador de peticiones (ventana deslizante de 60 s, en memoria).
Con varios workers o instancias, cada proceso lleva su propia cuenta: para un límite global
usa Redis o el rate limit de tu proxy (Caddy / Nginx)."""
import time
from collections import defaultdict, deque


class Limiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque] = defaultdict(deque)

    def allow(self, key: str, limit: int) -> bool:
        now = time.monotonic()
        q = self._hits[key]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True

    def reset(self) -> None:
        self._hits.clear()


client_limiter = Limiter()  # /v1/*
login_limiter = Limiter()   # login del panel y de la API admin


def reset_all() -> None:
    client_limiter.reset()
    login_limiter.reset()
