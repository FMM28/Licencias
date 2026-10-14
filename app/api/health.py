from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.db import get_engine
from app.db import migrate

router = APIRouter(tags=["health"])


@router.get("/health")
def liveness():
    """El proceso está vivo (no toca la base de datos)."""
    return {"status": "ok"}


@router.get("/health/ready")
def readiness():
    """Listo para atender: la BD responde y el esquema está en la última migración."""
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        current, head = migrate.current_revision(), migrate.head_revision()
    except Exception:  # noqa: BLE001 - cualquier falla significa "no listo"
        return JSONResponse(status_code=503, content={"status": "error", "db": "unreachable"})
    if current != head:
        return JSONResponse(status_code=503, content={
            "status": "error", "db": "ok", "schema": "outdated", "current": current, "head": head})
    return {"status": "ok", "db": "ok", "schema": head}
