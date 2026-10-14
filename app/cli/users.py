"""Usuarios del panel de administración desde la consola (sirve para crear el primero)."""
import sys

from app.cli._common import actor, fmt_date, read_password
from app.core import security
from app.db import new_session
from app.services import users as svc


def _user(db, username):
    user = svc.get_by_username(db, username)
    if not user:
        sys.exit(f"No existe el usuario «{username}».")
    return user


def cmd_create(args):
    db = new_session()
    password = read_password(args.password_stdin)
    try:
        user = svc.create_user(db, username=args.username, password=password, role=args.role,
                               must_change=args.must_change, actor=actor())
    except ValueError as exc:
        sys.exit(f"Error: {exc}")
    print(f"Usuario «{user.username}» creado con rol {user.role}.")


def cmd_list(args):
    db = new_session()
    print(f"{'USUARIO':<22}{'ROL':<10}{'ACTIVO':<8}{'ÚLTIMO ACCESO':<16}")
    for u in svc.list_users(db):
        print(f"{u.username:<22}{u.role:<10}{'sí' if u.is_active else 'no':<8}"
              f"{fmt_date(u.last_login_at):<16}")


def cmd_passwd(args):
    db = new_session()
    user = _user(db, args.username)
    password = read_password(args.password_stdin)
    try:
        svc.reset_password(db, user.id, password, actor=actor())
    except ValueError as exc:
        sys.exit(f"Error: {exc}")
    print("Contraseña restablecida. Sus sesiones se cerraron y deberá cambiarla al entrar.")


def cmd_role(args):
    db = new_session()
    user = _user(db, args.username)
    try:
        svc.set_role(db, user.id, args.role, actor=actor())
    except ValueError as exc:
        sys.exit(f"Error: {exc}")
    print("Listo.")


def cmd_toggle(active: bool):
    def run(args):
        db = new_session()
        user = _user(db, args.username)
        try:
            svc.set_active(db, user.id, active, actor=actor())
        except ValueError as exc:
            sys.exit(f"Error: {exc}")
        print("Usuario activado." if active else "Usuario desactivado y sesiones cerradas.")
    return run


def register(sub):
    u = sub.add_parser("user", help="usuarios del panel").add_subparsers(
        dest="user_cmd", required=True)

    s = u.add_parser("create", help="crea un usuario (pide la contraseña)")
    s.add_argument("username")
    s.add_argument("--role", choices=security.ROLES, default="admin")
    s.add_argument("--password-stdin", action="store_true",
                   help="lee la contraseña de la entrada estándar (para automatizar)")
    s.add_argument("--must-change", action="store_true",
                   help="obliga a cambiar la contraseña en el primer acceso")
    s.set_defaults(fn=cmd_create)

    s = u.add_parser("list", help="lista usuarios")
    s.set_defaults(fn=cmd_list)

    s = u.add_parser("passwd", help="restablece la contraseña")
    s.add_argument("username")
    s.add_argument("--password-stdin", action="store_true")
    s.set_defaults(fn=cmd_passwd)

    s = u.add_parser("role", help="cambia el rol")
    s.add_argument("username")
    s.add_argument("role", choices=security.ROLES)
    s.set_defaults(fn=cmd_role)

    s = u.add_parser("disable", help="desactiva y cierra sesiones")
    s.add_argument("username")
    s.set_defaults(fn=cmd_toggle(False))

    s = u.add_parser("enable", help="reactiva")
    s.add_argument("username")
    s.set_defaults(fn=cmd_toggle(True))
