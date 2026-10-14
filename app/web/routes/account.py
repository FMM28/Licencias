"""«Mi cuenta»: cambio de contraseña y sesiones abiertas."""
from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_db, require_perm
from app.core import security
from app.services import auth as auth_service
from app.services import users as user_service
from app.web import flash
from app.web.routes._helpers import redirect
from app.web.templating import render

router = APIRouter(prefix="/account", include_in_schema=False)
SESSION_ONLY = Depends(require_perm(None, allow_pending_password=True))


def _page(request: Request, ctx: AuthContext, db: Session, **extra):
    return render(request, "account.html", ctx, db,
                  sessions=auth_service.list_sessions(db, ctx.user.id),
                  current_session=ctx.session.id, forced=ctx.user.must_change_password,
                  min_len=security.MIN_PASSWORD_LENGTH, **extra)


@router.get("")
def account_page(request: Request, ctx: AuthContext = SESSION_ONLY,
                 db: Session = Depends(get_db)):
    return _page(request, ctx, db)


@router.post("/password")
def account_password(request: Request, current: str = Form(""), new: str = Form(""),
                     confirm: str = Form(""), ctx: AuthContext = SESSION_ONLY,
                     db: Session = Depends(get_db)):
    try:
        if new != confirm:
            raise ValueError("La confirmación no coincide con la contraseña nueva")
        user_service.change_password(db, ctx.user, current, new, keep_session_id=ctx.session.id)
    except ValueError as exc:
        db.rollback()
        return _page(request, ctx, db, status_code=422, error=str(exc))
    flash.push(db, ctx.session, ctx.token, "success",
               "Contraseña actualizada. Se cerraron tus demás sesiones.")
    return redirect("/admin")


@router.post("/sessions/revoke-others")
def revoke_other_sessions(ctx: AuthContext = SESSION_ONLY, db: Session = Depends(get_db)):
    n = auth_service.destroy_user_sessions(db, ctx.user.id, keep_id=ctx.session.id)
    db.commit()
    flash.push(db, ctx.session, ctx.token, "success", f"{n} sesión(es) cerrada(s).")
    return redirect("/admin/account")
