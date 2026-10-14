import getpass
import sys

from app.services import licenses as license_service


def actor() -> str:
    """Quién aparece en la bitácora cuando el cambio se hace desde la consola."""
    try:
        return f"cli:{getpass.getuser()}"
    except Exception:  # noqa: BLE001
        return "cli"


def fmt_date(dt) -> str:
    return "—" if dt is None else dt.strftime("%Y-%m-%d")


STATUS_TEXT = {"active": "activa", "expiring": "por vencer", "grace": "EN GRACIA",
               "expired": "VENCIDA", "revoked": "REVOCADA"}


def status_text(lic) -> str:
    return STATUS_TEXT[license_service.license_status(lic)]


def read_password(from_stdin: bool) -> str:
    """Contraseña sin dejarla en el historial de la shell: pedirla o leerla de stdin."""
    if from_stdin:
        return sys.stdin.readline().rstrip("\r\n")
    first = getpass.getpass("Contraseña: ")
    if first != getpass.getpass("Repite la contraseña: "):
        sys.exit("Las contraseñas no coinciden.")
    return first


__all__ = ["actor", "fmt_date", "status_text", "read_password"]
