"""Punto de entrada: `uvicorn app.main:app`.

Capas (de adentro hacia afuera):
  core/      configuración, criptografía, seguridad, errores (sin dependencias del resto)
  db/        motor y sesiones SQLAlchemy, migraciones Alembic
  models/    tablas
  schemas/   contratos Pydantic de la API
  services/  reglas de negocio (las usan API, panel y CLI)
  api/       endpoints JSON: /v1 (clientes) y /api/admin (administración)
  web/       panel HTML (/admin): rutas, plantillas Jinja2 y estáticos Tailwind
  cli/       gestión desde consola
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api import error_handlers, health
from app.api.admin import router as admin_api_router
from app.api.v1 import router as client_api_router
from app.core import crypto, middleware
from app.core.config import get_settings
from app.db import migrate, session_factory
from app.web.routes import public as web_public
from app.web.routes import router as web_router
from app.web.templating import STATIC_DIR


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    session_factory()  # abre el pool de conexiones
    if settings.auto_migrate:
        migrate.upgrade()
    elif not migrate.is_up_to_date():
        raise RuntimeError("La base de datos no está en la última migración. "
                           "Ejecuta `python -m app.cli db upgrade` (o LICENSE_AUTO_MIGRATE=true).")
    crypto.load_signing_key(settings)  # falla rápido si falta la clave privada
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Servicio de licencias", version="2.0.0", lifespan=lifespan,
        docs_url="/docs" if settings.docs_enabled else None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
        redoc_url=None,
    )
    error_handlers.register(app)
    middleware.register(app)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.include_router(health.router)
    app.include_router(client_api_router)   # /v1/...        SDK de los clientes
    app.include_router(admin_api_router)    # /api/admin/... administración (JSON)
    app.include_router(web_public)          # /admin/login
    app.include_router(web_router)          # /admin/...     panel HTML
    return app


app = create_app()
