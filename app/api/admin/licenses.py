from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.admin._util import invalid_as_422, license_out
from app.api.deps import AuthContext, get_db, require_perm
from app.schemas.admin import (ExtendIn, LicenseCreatedOut, LicenseCreateIn, LicenseOut,
                               LicensePage, LicenseUpdateIn, StatsOut, Status)
from app.services import licenses as license_service

router = APIRouter()  # sin prefijo: define /stats y /licenses


@router.get("/stats", response_model=StatsOut)
def stats(ctx: AuthContext = Depends(require_perm("licenses:read")), db: Session = Depends(get_db)):
    return license_service.stats(db)


@router.get("/licenses", response_model=LicensePage)
def list_licenses(q: str | None = None, status: Status | None = None, product: str | None = None,
                  page: int = Query(1, ge=1), per_page: int = Query(25, ge=1, le=100),
                  ctx: AuthContext = Depends(require_perm("licenses:read")),
                  db: Session = Depends(get_db)):
    rows, total = license_service.list_licenses_page(
        db, q=q, status=status, product=product, page=page, per_page=per_page)
    return LicensePage(items=[license_out(r) for r in rows], total=total, page=page,
                       per_page=per_page)


@router.post("/licenses", response_model=LicenseCreatedOut, status_code=201)
def create_license(body: LicenseCreateIn,
                   ctx: AuthContext = Depends(require_perm("licenses:write")),
                   db: Session = Depends(get_db)):
    with invalid_as_422():
        lic, key = license_service.create_license(db, **body.model_dump(),
                                                  actor=ctx.user.username)
    return LicenseCreatedOut(license=license_out(lic), license_key=key)


@router.get("/licenses/{license_id}", response_model=LicenseOut)
def get_license(license_id: str, ctx: AuthContext = Depends(require_perm("licenses:read")),
                db: Session = Depends(get_db)):
    return license_out(license_service.get_license(db, license_id))


@router.patch("/licenses/{license_id}", response_model=LicenseOut)
def update_license(license_id: str, body: LicenseUpdateIn,
                   ctx: AuthContext = Depends(require_perm("licenses:write")),
                   db: Session = Depends(get_db)):
    changes = body.model_dump(exclude_unset=True)
    with invalid_as_422():
        if "max_activations" in changes and changes["max_activations"] is not None:
            license_service.set_max_activations(db, license_id, changes["max_activations"],
                                                actor=ctx.user.username)
        if "notes" in changes:
            license_service.update_notes(db, license_id, changes["notes"], actor=ctx.user.username)
    return license_out(license_service.get_license(db, license_id))


@router.post("/licenses/{license_id}/revoke", response_model=LicenseOut)
def revoke(license_id: str, ctx: AuthContext = Depends(require_perm("licenses:write")),
           db: Session = Depends(get_db)):
    return license_out(license_service.set_revoked(db, license_id, True, actor=ctx.user.username))


@router.post("/licenses/{license_id}/unrevoke", response_model=LicenseOut)
def unrevoke(license_id: str, ctx: AuthContext = Depends(require_perm("licenses:write")),
             db: Session = Depends(get_db)):
    return license_out(license_service.set_revoked(db, license_id, False, actor=ctx.user.username))


@router.post("/licenses/{license_id}/extend", response_model=LicenseOut)
def extend(license_id: str, body: ExtendIn,
           ctx: AuthContext = Depends(require_perm("licenses:write")),
           db: Session = Depends(get_db)):
    with invalid_as_422():
        lic = license_service.extend_license(db, license_id, body.days, actor=ctx.user.username)
    return license_out(lic)


@router.delete("/licenses/{license_id}/activations")
def release(license_id: str, fingerprint: str | None = None,
            ctx: AuthContext = Depends(require_perm("licenses:write")),
            db: Session = Depends(get_db)):
    """Libera una instalación (o todas si no se indica `fingerprint`)."""
    n = license_service.release_activation(db, license_id, fingerprint, actor=ctx.user.username)
    return {"released": n}
