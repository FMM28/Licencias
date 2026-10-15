"""API pública que usa el SDK instalado en el servidor del cliente."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import client_ip, get_db, limit_client
from app.core import crypto
from app.core.config import get_settings
from app.models import License
from app.schemas.client import AbortIn, ActivateIn, ConfirmIn, DeactivateIn, TokenOut, ValidateIn
from app.core.timeutil import to_ts
from app.services import activation

router = APIRouter(prefix="/v1", tags=["client"], dependencies=[Depends(limit_client)])


def _token_out(lic: License, token: str, exp: int) -> TokenOut:
    return TokenOut(token=token, token_expires_at=exp, plan=lic.plan, features=lic.features,
                    license_expires_at=to_ts(lic.expires_at))


@router.get("/public-key")
def public_key():
    """Solo informativo: el SDK debe llevar la clave pública embebida, no pedirla."""
    return {"alg": "Ed25519", "public_key": crypto.public_key_b64(get_settings())}


@router.post("/activate", response_model=TokenOut)
def activate(body: ActivateIn, request: Request, db: Session = Depends(get_db)):
    lic, token, exp = activation.activate(
        db, key=body.license_key, product=body.product, fingerprint=body.fingerprint,
        hostname=body.hostname, ip=client_ip(request),
        two_phase=body.two_phase)
    return _token_out(lic, token, exp)


@router.post("/activate/confirm")
def activate_confirm(body: ConfirmIn, request: Request, db: Session = Depends(get_db)):
    activation.confirm(db, key=body.license_key, fingerprint=body.fingerprint,
                       ip=client_ip(request))
    return {"ok": True}


@router.post("/activate/abort")
def activate_abort(body: AbortIn, request: Request, db: Session = Depends(get_db)):
    activation.abort(db, key=body.license_key, fingerprint=body.fingerprint,
                     reason=body.reason, ip=client_ip(request))
    return {"ok": True}


@router.post("/validate", response_model=TokenOut)
def validate(body: ValidateIn, request: Request, db: Session = Depends(get_db)):
    lic, token, exp = activation.refresh(
        db, key=body.license_key, product=body.product, fingerprint=body.fingerprint,
        ip=client_ip(request))
    return _token_out(lic, token, exp)


@router.post("/deactivate")
def deactivate(body: DeactivateIn, request: Request, db: Session = Depends(get_db)):
    activation.deactivate(db, key=body.license_key, fingerprint=body.fingerprint,
                          ip=client_ip(request))
    return {"ok": True}
