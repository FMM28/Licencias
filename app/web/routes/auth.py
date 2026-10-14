"""Login y logout del panel."""
from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session

from app.api.deps import (AuthContext, clear_session_cookie, client_ip, get_db, optional_ctx,
                          require_ctx, same_origin_check, set_session_cookie)
from app.core.config import get_settings
from app.core.errors import AuthError
from app.core.ratelimit import login_limiter
from app.services import auth as auth_service
from app.services.audit import audit
from app.web.routes._helpers import redirect, safe_next
from app.web.templating import render

# `public`: sin sesión (login). `router`: con sesión y CSRF (logout).
public = APIRouter(prefix="/admin", include_in_schema=False)
router = APIRouter(include_in_schema=False)


@public.get("/login")
def login_page(request: Request, next: str = "", ctx: AuthContext | None = Depends(optional_ctx)):
    if ctx:
        return redirect("/admin")
    return render(request, "login.html", next=safe_next(next))


@public.post("/login")
def login(request: Request, username: str = Form(""), password: str = Form(""),
          next: str = Form(""), db: Session = Depends(get_db)):
    same_origin_check(request)
    ip = client_ip(request)
    if not login_limiter.allow(ip, get_settings().login_rate_limit_per_min):
        return render(request, "login.html", status_code=429, next=safe_next(next),
                      username=username, error="Demasiados intentos. Espera un minuto.")
    try:
        user, token, _ = auth_service.authenticate(
            db, username, password, ip, request.headers.get("user-agent"))
    except AuthError as exc:
        return render(request, "login.html", status_code=401, next=safe_next(next),
                      username=username, error=exc.message)
    response = redirect("/admin/account" if user.must_change_password
                        else safe_next(next) or "/admin")
    set_session_cookie(response, token)
    return response


@router.post("/logout")
def logout(request: Request, ctx: AuthContext = Depends(require_ctx),
           db: Session = Depends(get_db)):
    auth_service.destroy_session(db, ctx.token)
    audit(db, "admin_logout", ip=client_ip(request), actor=ctx.user.username)
    db.commit()
    response = redirect("/admin/login")
    clear_session_cookie(response)
    return response
