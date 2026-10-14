"""Traduce las excepciones del dominio a respuestas: JSON para /v1 y /api/…,
redirección o página de error para el panel HTML."""
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.deps import clear_session_cookie
from app.core.errors import (ApiError, CSRFError, Forbidden, NotAuthenticated, PageNotFound,
                             PasswordChangeRequired)


def _wants_json(request: Request) -> bool:
    return not request.url.path.startswith("/admin")


def _json(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def _page(request: Request, status: int, title: str, message: str):
    from app.web.templating import render_error  # import tardío: evita ciclos
    return render_error(request, status, title, message)


def register(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError):
        return _json(exc.status, exc.code, exc.message)

    @app.exception_handler(NotAuthenticated)
    async def _not_authenticated(request: Request, exc: NotAuthenticated):
        if _wants_json(request):
            return _json(401, "unauthenticated", "Inicia sesión para continuar")
        target = "/admin/login"
        if request.method == "GET" and request.url.path != "/admin/login":
            nxt = request.url.path + (f"?{request.url.query}" if request.url.query else "")
            target += f"?next={quote(nxt)}"
        response = RedirectResponse(target, status_code=303)
        clear_session_cookie(response)  # por si quedó una cookie vencida
        return response

    @app.exception_handler(Forbidden)
    async def _forbidden(request: Request, exc: Forbidden):
        if _wants_json(request):
            return _json(403, "forbidden", exc.message)
        return _page(request, 403, "Acceso denegado", exc.message)

    @app.exception_handler(PasswordChangeRequired)
    async def _password_change(request: Request, exc: PasswordChangeRequired):
        if _wants_json(request):
            return _json(403, "password_change_required",
                         "Debes cambiar tu contraseña antes de continuar")
        return RedirectResponse("/admin/account", status_code=303)

    @app.exception_handler(CSRFError)
    async def _csrf(request: Request, exc: CSRFError):
        message = ("La solicitud no es válida o el formulario caducó. "
                   "Recarga la página e inténtalo de nuevo.")
        if _wants_json(request):
            return _json(403, "csrf", message)
        return _page(request, 403, "Solicitud rechazada", message)

    @app.exception_handler(PageNotFound)
    async def _not_found(request: Request, exc: PageNotFound):
        if _wants_json(request):
            return _json(404, "not_found", "No encontrado")
        return _page(request, 404, "No encontrado", "Lo que buscas no existe o fue eliminado.")

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception(request: Request, exc: StarletteHTTPException):
        # Rutas desconocidas dentro del panel: página de error con el mismo diseño.
        if exc.status_code == 404 and not _wants_json(request):
            return _page(request, 404, "No encontrado", "Esa página no existe.")
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail},
                            headers=getattr(exc, "headers", None))
