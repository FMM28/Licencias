from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.admin._util import invalid_as_422
from app.api.deps import AuthContext, get_db, require_perm
from app.core import security
from app.core.errors import ApiError
from app.schemas.admin import (PasswordResetIn, PasswordResetOut, UserCreatedOut, UserCreateIn,
                               UserOut, UserUpdateIn)
from app.services import users as user_service

router = APIRouter(prefix="/users")
MANAGE = Depends(require_perm("users:manage"))


def _not_self(ctx: AuthContext, user_id: int) -> None:
    if ctx.user.id == user_id:
        raise ApiError("forbidden", "No puedes modificar tu propia cuenta desde aquí", 403)


@router.get("", response_model=list[UserOut])
def list_users(ctx: AuthContext = MANAGE, db: Session = Depends(get_db)):
    return [UserOut.model_validate(u, from_attributes=True) for u in user_service.list_users(db)]


@router.post("", response_model=UserCreatedOut, status_code=201)
def create_user(body: UserCreateIn, ctx: AuthContext = MANAGE, db: Session = Depends(get_db)):
    generated = not body.password
    password = body.password or security.generate_password()
    with invalid_as_422():
        user = user_service.create_user(db, username=body.username, password=password,
                                        role=body.role, must_change=True, actor=ctx.user.username)
    return UserCreatedOut(user=UserOut.model_validate(user, from_attributes=True),
                          temporary_password=password if generated else None)


@router.patch("/{user_id}", response_model=UserOut)
def update_user(user_id: int, body: UserUpdateIn, ctx: AuthContext = MANAGE,
                db: Session = Depends(get_db)):
    _not_self(ctx, user_id)
    with invalid_as_422():
        user = user_service.get_user(db, user_id)
        if user is None:
            raise ApiError("not_found", "Usuario no encontrado", 404)
        if body.role is not None:
            user = user_service.set_role(db, user_id, body.role, actor=ctx.user.username)
        if body.is_active is not None:
            user = user_service.set_active(db, user_id, body.is_active, actor=ctx.user.username)
    return UserOut.model_validate(user, from_attributes=True)


@router.post("/{user_id}/reset-password", response_model=PasswordResetOut)
def reset_password(user_id: int, body: PasswordResetIn, ctx: AuthContext = MANAGE,
                   db: Session = Depends(get_db)):
    _not_self(ctx, user_id)
    generated = not body.password
    password = body.password or security.generate_password()
    with invalid_as_422():
        user_service.reset_password(db, user_id, password, actor=ctx.user.username)
    return PasswordResetOut(temporary_password=password if generated else None)
