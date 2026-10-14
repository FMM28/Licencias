"""Excepciones del dominio. Se traducen a respuestas HTTP en app/api/error_handlers.py."""


class ApiError(Exception):
    """Error con código estable para clientes de la API: {"error": {"code", "message"}}."""

    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


class LicenseError(ApiError):
    """Fallas de negocio de las licencias (revocada, vencida, límite de activaciones…)."""

    def __init__(self, code: str, message: str, status: int = 403):
        super().__init__(code, message, status)


class AuthError(Exception):
    """Credenciales inválidas (mensaje genérico a propósito)."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class NotAuthenticated(Exception):
    """No hay sesión válida."""


class Forbidden(Exception):
    """Hay sesión, pero el rol no tiene el permiso."""

    def __init__(self, message: str = "No tienes permiso para hacer esto"):
        super().__init__(message)
        self.message = message


class PasswordChangeRequired(Exception):
    """La cuenta debe cambiar su contraseña antes de seguir."""


class CSRFError(Exception):
    """Origen o token CSRF inválido."""


class PageNotFound(Exception):
    """Recurso inexistente (se muestra como página o como JSON según la ruta)."""
