"""API JSON de administración bajo /api/admin.

Autenticación: cookie de sesión (POST /api/admin/auth/login).
Autorización:  permisos por rol en cada endpoint (viewer < operator < admin).
CSRF:          todo POST/PATCH/DELETE exige la cabecera X-CSRF-Token que devuelve el login.
"""
from fastapi import APIRouter, Depends

from app.api.admin import audit, auth, licenses, users
from app.api.deps import csrf_check

router = APIRouter(prefix="/api/admin", tags=["admin"])
router.include_router(auth.public)  # login: sin CSRF (todavía no hay sesión)

protected = APIRouter(dependencies=[Depends(csrf_check)])
protected.include_router(auth.router)
protected.include_router(licenses.router)
protected.include_router(users.router)
protected.include_router(audit.router)
router.include_router(protected)
