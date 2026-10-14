"""Gestión de los usuarios del panel (solo rol administrador)."""
from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, get_db, require_perm
from app.core import security
from app.services import users as user_service
from app.web import flash
from app.web.routes._helpers import redirect
from app.web.templating import render

router = APIRouter(prefix="/users", include_in_schema=False)
MANAGE = Depends(require_perm("users:manage"))


@router.get("")
def users_page(request: Request, ctx: AuthContext = MANAGE, db: Session = Depends(get_db)):
    return render(request, "users.html", ctx, db, users=user_service.list_users(db),
                  form={"role": "operator"})


@router.post("")
def user_create(request: Request, username: str = Form(""), role: str = Form("viewer"),
                password: str = Form(""), ctx: AuthContext = MANAGE,
                db: Session = Depends(get_db)):
    generated = not password
    password = password or security.generate_password()
    try:
        user = user_service.create_user(db, username=username, password=password, role=role,
                                        must_change=True, actor=ctx.user.username)
    except ValueError as exc:
        return render(request, "users.html", ctx, db, status_code=422, error=str(exc),
                      users=user_service.list_users(db), form={"username": username, "role": role})
    text = f"Usuario «{user.username}» creado. Deberá cambiar la contraseña al entrar."
    if generated:
        flash.push(db, ctx.session, ctx.token, "secret", text, secret=password,
                   secret_label="Contraseña temporal")
    else:
        flash.push(db, ctx.session, ctx.token, "success", text)
    return redirect("/admin/users")


def _user_action(ctx: AuthContext, db: Session, user_id: int, ok: str | None, action):
    """Acciones sobre otros usuarios. `ok=None` si la propia acción deja el mensaje."""
    try:
        if user_id == ctx.user.id:
            raise ValueError("No puedes modificar tu propia cuenta desde aquí "
                             "(usa «Mi cuenta» para cambiar tu contraseña)")
        action()
        if ok:
            flash.push(db, ctx.session, ctx.token, "success", ok)
    except ValueError as exc:
        db.rollback()
        flash.push(db, ctx.session, ctx.token, "error", str(exc))
    return redirect("/admin/users")


@router.post("/{user_id}/role")
def user_role(user_id: int, role: str = Form(""), ctx: AuthContext = MANAGE,
              db: Session = Depends(get_db)):
    return _user_action(ctx, db, user_id, "Rol actualizado.",
                        lambda: user_service.set_role(db, user_id, role, actor=ctx.user.username))


@router.post("/{user_id}/active")
def user_active(user_id: int, active: str = Form("false"), ctx: AuthContext = MANAGE,
                db: Session = Depends(get_db)):
    enable = active == "true"
    return _user_action(
        ctx, db, user_id,
        "Usuario activado." if enable else "Usuario desactivado y sesiones cerradas.",
        lambda: user_service.set_active(db, user_id, enable, actor=ctx.user.username))


@router.post("/{user_id}/reset-password")
def user_reset(user_id: int, password: str = Form(""), ctx: AuthContext = MANAGE,
               db: Session = Depends(get_db)):
    generated = not password
    password = password or security.generate_password()

    def action():
        user_service.reset_password(db, user_id, password, actor=ctx.user.username)
        text = "Contraseña restablecida. Sus sesiones se cerraron y deberá cambiarla al entrar."
        if generated:
            flash.push(db, ctx.session, ctx.token, "secret", text, secret=password,
                       secret_label="Contraseña temporal")
        else:
            flash.push(db, ctx.session, ctx.token, "success", text)
    return _user_action(ctx, db, user_id, None, action)
