import math

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_db, require_perm
from app.services import audit as audit_service
from app.web.templating import render

router = APIRouter(prefix="/audit", include_in_schema=False)


@router.get("")
def audit_page(request: Request, license: str = "", event: str = "", actor: str = "",
               page: int = 1, ctx: AuthContext = Depends(require_perm("audit:read")),
               db: Session = Depends(get_db)):
    page = max(page, 1)
    rows, total = audit_service.list_audit(db, license_id=license or None, event=event or None,
                                           actor=actor or None, page=page, per_page=50)
    return render(request, "audit.html", ctx, db, rows=rows, total=total, page=page,
                  pages=max(1, math.ceil(total / 50)), license=license, event=event,
                  actor=actor, events=audit_service.audit_events(db))
