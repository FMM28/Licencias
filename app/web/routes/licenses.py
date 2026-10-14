"""Alta, consulta y gestión de licencias desde el panel."""
import math

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_db, require_perm
from app.core.config import get_settings
from app.core.errors import LicenseError, PageNotFound
from app.services import audit as audit_service
from app.services import licenses as license_service
from app.web import flash
from app.web.routes._helpers import (PER_PAGE, PRODUCT_RE, get_license_or_404, parse_features,
                                     redirect, to_int)
from app.web.templating import render

router = APIRouter(prefix="/licenses", include_in_schema=False)
READ = Depends(require_perm("licenses:read"))
WRITE = Depends(require_perm("licenses:write"))


@router.get("")
def licenses(request: Request, q: str = "", status: str = "", product: str = "", page: int = 1,
             ctx: AuthContext = READ, db: Session = Depends(get_db)):
    page = max(page, 1)
    rows, total = license_service.list_licenses_page(
        db, q=q, status=status or None, product=product or None, page=page, per_page=PER_PAGE)
    return render(request, "licenses.html", ctx, db, rows=rows, total=total, page=page,
                  pages=max(1, math.ceil(total / PER_PAGE)), q=q, status=status,
                  product=product, products=license_service.list_products(db))


@router.get("/new")  # antes que /{license_id}, si no "new" se tomaría como un id
def license_new(request: Request, ctx: AuthContext = WRITE, db: Session = Depends(get_db)):
    return render(request, "license_new.html", ctx, db, products=license_service.list_products(db),
                  form={"plan": "subscription", "days": "365", "max_activations": "1"})


@router.post("")
def license_create(
        request: Request, product: str = Form(""), customer: str = Form(""),
        email: str = Form(""), plan: str = Form("subscription"), days: str = Form(""),
        max_activations: str = Form("1"), features: str = Form(""), notes: str = Form(""),
        ctx: AuthContext = WRITE, db: Session = Depends(get_db)):
    form = dict(product=product, customer=customer, email=email, plan=plan, days=days,
                max_activations=max_activations, features=features, notes=notes)
    try:
        product = product.strip()
        if not PRODUCT_RE.match(product):
            raise ValueError("Producto inválido (letras, números, punto, guion; máx. 64)")
        if not customer.strip() or len(customer) > 200:
            raise ValueError("El cliente es obligatorio (máx. 200 caracteres)")
        if email.strip() and ("@" not in email or len(email) > 200):
            raise ValueError("El correo no parece válido")
        if len(notes) > 2000:
            raise ValueError("Las notas son demasiado largas (máx. 2000)")
        lic, key = license_service.create_license(
            db, product=product, customer=customer, email=email, plan=plan,
            features=parse_features(features),
            max_activations=to_int(max_activations, "Instalaciones permitidas", maximum=1000),
            days=to_int(days, "Duración", maximum=3650) if plan != "perpetual" else None,
            notes=notes, actor=ctx.user.username)
    except ValueError as exc:
        return render(request, "license_new.html", ctx, db, status_code=422, error=str(exc),
                      form=form, products=license_service.list_products(db))
    flash.push(db, ctx.session, ctx.token, "secret", f"Licencia creada para {lic.customer}.",
               secret=key, secret_label="Clave de licencia")
    return redirect(f"/admin/licenses/{lic.id}")


@router.get("/{license_id}")
def license_detail(request: Request, license_id: str, ctx: AuthContext = READ,
                   db: Session = Depends(get_db)):
    lic = get_license_or_404(db, license_id)
    history = audit_service.list_audit(db, license_id=lic.id, per_page=15)[0] \
        if ctx.can("audit:read") else []
    activations = sorted(lic.activations, key=lambda a: (not a.active, -a.last_seen.timestamp()))
    settings = get_settings()
    return render(request, "license_detail.html", ctx, db, lic=lic,
                  status=license_service.license_status(lic), activations=activations,
                  active=sum(1 for a in activations if a.active), history=history,
                  grace_days=settings.expiry_grace_days, ttl_days=settings.token_ttl_days)


def _do(ctx: AuthContext, db: Session, license_id: str, ok: str, action):
    """Ejecuta una acción sobre una licencia, deja un mensaje y vuelve a la ficha."""
    try:
        action()
        flash.push(db, ctx.session, ctx.token, "success", ok)
    except LicenseError:
        raise PageNotFound() from None
    except ValueError as exc:
        db.rollback()
        flash.push(db, ctx.session, ctx.token, "error", str(exc))
    return redirect(f"/admin/licenses/{license_id}")


@router.post("/{license_id}/extend")
def license_extend(license_id: str, days: str = Form(""), ctx: AuthContext = WRITE,
                   db: Session = Depends(get_db)):
    def action():
        license_service.extend_license(db, license_id, to_int(days, "Los días", maximum=3650),
                                       actor=ctx.user.username)
    return _do(ctx, db, license_id, f"Licencia renovada {days.strip()} días.", action)


@router.post("/{license_id}/revoke")
def license_revoke(license_id: str, ctx: AuthContext = WRITE, db: Session = Depends(get_db)):
    return _do(ctx, db, license_id,
               "Licencia revocada. El cliente la perderá en su próxima validación.",
               lambda: license_service.set_revoked(db, license_id, True, actor=ctx.user.username))


@router.post("/{license_id}/unrevoke")
def license_unrevoke(license_id: str, ctx: AuthContext = WRITE, db: Session = Depends(get_db)):
    return _do(ctx, db, license_id, "Licencia reactivada.",
               lambda: license_service.set_revoked(db, license_id, False, actor=ctx.user.username))


@router.post("/{license_id}/release")
def license_release(license_id: str, fingerprint: str = Form(""), ctx: AuthContext = WRITE,
                    db: Session = Depends(get_db)):
    return _do(ctx, db, license_id, "Activación liberada.",
               lambda: license_service.release_activation(db, license_id, fingerprint or None,
                                                          actor=ctx.user.username))


@router.post("/{license_id}/max")
def license_max(license_id: str, n: str = Form(""), ctx: AuthContext = WRITE,
                db: Session = Depends(get_db)):
    def action():
        license_service.set_max_activations(db, license_id, to_int(n, "El máximo", maximum=1000),
                                            actor=ctx.user.username)
    return _do(ctx, db, license_id, "Límite de instalaciones actualizado.", action)


@router.post("/{license_id}/notes")
def license_notes(license_id: str, notes: str = Form(""), ctx: AuthContext = WRITE,
                  db: Session = Depends(get_db)):
    def action():
        if len(notes) > 2000:
            raise ValueError("Las notas son demasiado largas (máx. 2000)")
        license_service.update_notes(db, license_id, notes, actor=ctx.user.username)
    return _do(ctx, db, license_id, "Notas guardadas.", action)
