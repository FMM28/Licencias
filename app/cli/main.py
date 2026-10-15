"""Consola de administración:  python -m app.cli <comando>   (o `licensectl` si instalaste el paquete)"""
import argparse
import sys

from app.cli import database, keys, licenses, users
from app.core.errors import LicenseError


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="licensectl", description="Gestión del servicio de licencias")
    sub = p.add_subparsers(dest="cmd", required=True)
    for module in (keys, database, users, licenses):
        module.register(sub)
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        args.fn(args)
    except LicenseError as exc:
        sys.exit(f"Error: {exc.message}")
    except ValueError as exc:          # configuración inválida (p. ej. falta LICENSE_DB_URL)
        sys.exit(f"Error de configuración: {exc}")


if __name__ == "__main__":
    main()
