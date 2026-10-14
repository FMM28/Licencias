"""Importar todos los modelos aquí garantiza que Base.metadata los conozca
(lo necesitan Alembic y las relaciones entre tablas)."""
from app.models.admin import AdminSession, AdminUser
from app.models.audit import AuditLog
from app.models.license import Activation, License

__all__ = ["AdminSession", "AdminUser", "AuditLog", "Activation", "License"]
