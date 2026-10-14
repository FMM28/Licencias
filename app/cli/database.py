"""Migraciones de base de datos (envoltorio de Alembic)."""
import sys

from app.core.config import get_settings
from app.db import migrate
from app.db.session import normalize_url


def _target() -> str:
    url = normalize_url(get_settings().db_url)
    return url.split("@")[-1] if "@" in url else url  # sin usuario ni contraseña


def cmd_upgrade(args):
    migrate.upgrade(revision=args.revision)
    print(f"Base de datos ({_target()}) en la revisión: {migrate.current_revision()}")


def cmd_downgrade(args):
    if not args.yes:
        sys.exit("Revertir una migración puede borrar datos. Repite con --yes si estás seguro.")
    migrate.downgrade(revision=args.revision)
    print(f"Base de datos ({_target()}) en la revisión: {migrate.current_revision()}")


def cmd_current(args):
    current, head = migrate.current_revision(), migrate.head_revision()
    print(f"Base de datos: {_target()}")
    print(f"Revisión actual: {current or '(sin migraciones aplicadas)'}   última disponible: {head}")
    print("Estado: " + ("al día" if current == head else "PENDIENTE → python -m app.cli db upgrade"))


def cmd_stamp(args):
    migrate.stamp(revision=args.revision)
    print(f"Marcada como {args.revision} (no se ejecutó ninguna migración).")


def cmd_check(args):
    try:
        migrate.check()
    except Exception as exc:  # noqa: BLE001
        sys.exit(f"Los modelos tienen cambios sin migración: {exc}")
    print("Los modelos coinciden con las migraciones.")


def register(sub):
    db = sub.add_parser("db", help="migraciones de base de datos").add_subparsers(
        dest="db_cmd", required=True)

    s = db.add_parser("upgrade", help="aplica migraciones pendientes")
    s.add_argument("revision", nargs="?", default="head")
    s.set_defaults(fn=cmd_upgrade)

    s = db.add_parser("downgrade", help="revierte (por defecto la última)")
    s.add_argument("revision", nargs="?", default="-1")
    s.add_argument("--yes", action="store_true")
    s.set_defaults(fn=cmd_downgrade)

    s = db.add_parser("current", help="muestra la revisión actual")
    s.set_defaults(fn=cmd_current)

    s = db.add_parser("stamp", help="marca la BD en una revisión sin ejecutar nada")
    s.add_argument("revision")
    s.set_defaults(fn=cmd_stamp)

    s = db.add_parser("check", help="comprueba que los modelos coinciden con las migraciones")
    s.set_defaults(fn=cmd_check)
