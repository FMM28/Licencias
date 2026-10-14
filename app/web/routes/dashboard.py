from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_db, require_perm
from app.services import audit as audit_service
from app.services import licenses as license_service
from app.web.templating import render


def dashboard(request: Request, ctx: AuthContext = Depends(require_perm("licenses:read")),
              db: Session = Depends(get_db)):
    """Resumen: cifras, licencias que requieren atención y actividad reciente."""
    grace, _ = license_service.list_licenses_page(db, status="grace", per_page=8, sort="expires")
    expiring, _ = license_service.list_licenses_page(db, status="expiring", per_page=8,
                                                     sort="expires")
    recent = audit_service.list_audit(db, per_page=10)[0] if ctx.can("audit:read") else []
    return render(request, "dashboard.html", ctx, db, stats=license_service.stats(db),
                  attention=(grace + expiring)[:8], recent=recent)
