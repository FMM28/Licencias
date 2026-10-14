"""Rutas HTML del panel (/admin).

`public`  : login (sin sesión; solo comprobación de origen).
`router`  : todo lo demás. Cada ruta exige sesión + permiso y, al modificar, token CSRF.
"""
from fastapi import APIRouter, Depends

from app.api.deps import csrf_check
from app.web.routes import account, audit, auth, dashboard, licenses, users

public = auth.public

router = APIRouter(prefix="/admin", include_in_schema=False, dependencies=[Depends(csrf_check)])
router.add_api_route("", dashboard.dashboard, methods=["GET"])
router.include_router(auth.router)
router.include_router(licenses.router)
router.include_router(audit.router)
router.include_router(users.router)
router.include_router(account.router)
