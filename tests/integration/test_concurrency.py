"""Carreras entre peticiones simultáneas (dependen del bloqueo de filas de InnoDB)."""
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import func, select

from app.models import Activation


def test_activation_limit_cannot_be_bypassed_with_parallel_requests(env):
    _, key = env.new_license(max_activations=2)

    def activate(i: int) -> int:
        r = env.new_http().post("/v1/activate", json={
            "license_key": key, "product": "mi-app", "fingerprint": f"{i:02d}" * 16})
        return r.status_code

    with ThreadPoolExecutor(max_workers=12) as pool:
        codes = list(pool.map(activate, range(12)))

    assert codes.count(200) == 2, codes              # exactamente el límite, nunca más
    assert codes.count(409) == 10, codes
    with env.db() as db:
        active = db.scalar(select(func.count()).select_from(Activation)
                           .where(Activation.active.is_(True)))
    assert active == 2
