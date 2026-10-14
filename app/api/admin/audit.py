from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_db, require_perm
from app.schemas.admin import AuditOut, AuditPage
from app.services import audit as audit_service

router = APIRouter(prefix="/audit")


@router.get("", response_model=AuditPage)
def list_audit(license_id: str | None = None, event: str | None = None, actor: str | None = None,
               page: int = Query(1, ge=1), per_page: int = Query(50, ge=1, le=200),
               ctx: AuthContext = Depends(require_perm("audit:read")),
               db: Session = Depends(get_db)):
    rows, total = audit_service.list_audit(db, license_id=license_id, event=event, actor=actor,
                                           page=page, per_page=per_page)
    return AuditPage(items=[AuditOut.model_validate(r, from_attributes=True) for r in rows],
                     total=total, page=page, per_page=per_page)
