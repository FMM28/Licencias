"""Cabeceras de seguridad. El panel y su API nunca se guardan en caché ni se pueden embeber."""
from fastapi import FastAPI, Request

from app.core.config import get_settings

ADMIN_CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
             "font-src 'self'; connect-src 'self'; form-action 'self'; frame-ancestors 'none'; "
             "base-uri 'none'")


def register(app: FastAPI) -> None:
    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        if path.startswith(("/admin", "/api/admin")):
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Frame-Options"] = "DENY"
            if path.startswith("/admin"):
                response.headers["Content-Security-Policy"] = ADMIN_CSP
        if get_settings().cookie_secure:
            response.headers.setdefault("Strict-Transport-Security",
                                        "max-age=31536000; includeSubDomains")
        return response
