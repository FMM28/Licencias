"""Gestión manual de licencias desde la consola."""
import sys

from sqlalchemy import select

from app.core.timeutil import utcnow
from app.cli._common import actor, fmt_date, status_text
from app.db import new_session
from app.models import AuditLog
from app.services import licenses as svc


def cmd_create(args):
    db = new_session()
    features = [f.strip() for f in (args.features or "").split(",") if f.strip()]
    try:
        lic, key = svc.create_license(
            db, product=args.product, customer=args.customer, email=args.email,
            plan=args.plan, features=features, max_activations=args.max_activations,
            days=args.days, notes=args.notes, actor=actor())
    except ValueError as exc:
        sys.exit(f"Error: {exc}")
    print(f"ID:        {lic.id}")
    print(f"Cliente:   {lic.customer}")
    print(f"Plan:      {lic.plan}   vence: {fmt_date(lic.expires_at)}")
    print("\nCLAVE DE LICENCIA (entrégala al cliente; no se podrá volver a ver):\n")
    print(f"  {key}\n")


def cmd_list(args):
    db = new_session()
    rows, total = svc.list_licenses_page(db, product=args.product, status=args.status,
                                         per_page=args.limit)
    if not rows:
        print("Sin licencias.")
        return
    print(f"{'ID':<17}{'PRODUCTO':<14}{'CLIENTE':<22}{'PLAN':<13}{'VENCE':<12}{'ACT':<6}ESTADO")
    for lic in rows:
        act = f"{svc.active_installs(lic)}/{lic.max_activations}"
        print(f"{lic.id:<17}{lic.product[:13]:<14}{lic.customer[:21]:<22}{lic.plan:<13}"
              f"{fmt_date(lic.expires_at):<12}{act:<6}{status_text(lic)}")
    if total > len(rows):
        print(f"… mostrando {len(rows)} de {total} (usa --limit)")


def cmd_show(args):
    db = new_session()
    lic = svc.get_license(db, args.id)
    print(f"{lic.id}  [{status_text(lic)}]")
    print(f"  producto: {lic.product}   plan: {lic.plan}   vence: {fmt_date(lic.expires_at)}")
    print(f"  cliente:  {lic.customer} <{lic.email or '-'}>")
    print(f"  features: {', '.join(lic.features) or '-'}   notas: {lic.notes or '-'}")
    print(f"  activaciones ({svc.active_installs(lic)}/{lic.max_activations}):")
    for a in lic.activations:
        mark = "●" if a.is_live(utcnow()) else "○"
        print(f"    {mark} {a.fingerprint[:16]}…  {a.hostname or '-':<20} ip={a.last_ip or '-':<16}"
              f" visto={a.last_seen:%Y-%m-%d %H:%M}")


def cmd_revoke(args):
    db = new_session()
    svc.set_revoked(db, args.id, not args.undo, actor=actor())
    print("Licencia reactivada." if args.undo
          else "Licencia revocada. Surtirá efecto en la próxima validación del cliente.")


def cmd_extend(args):
    db = new_session()
    try:
        lic = svc.extend_license(db, args.id, args.days, actor=actor())
    except ValueError as exc:
        sys.exit(f"Error: {exc}")
    print(f"Nuevo vencimiento: {fmt_date(lic.expires_at)}")


def cmd_release(args):
    db = new_session()
    n = svc.release_activation(db, args.id, args.fingerprint, actor=actor())
    print(f"{n} activación(es) liberada(s).")


def cmd_set_max(args):
    db = new_session()
    try:
        svc.set_max_activations(db, args.id, args.n, actor=actor())
    except ValueError as exc:
        sys.exit(f"Error: {exc}")
    print("Listo.")


def cmd_audit(args):
    db = new_session()
    stmt = select(AuditLog).order_by(AuditLog.id.desc()).limit(args.limit)
    if args.id:
        stmt = stmt.where(AuditLog.license_id == args.id)
    for r in db.scalars(stmt):
        print(f"{r.ts:%Y-%m-%d %H:%M:%S}  {r.license_id or '-':<17}{r.event:<20}"
              f"{r.actor or '-':<14}{r.ip or '-':<16}{r.detail or ''}")


def register(sub):
    s = sub.add_parser("create", help="crea una licencia")
    s.add_argument("--product", required=True)
    s.add_argument("--customer", required=True)
    s.add_argument("--email")
    s.add_argument("--plan", choices=svc.PLANS, default="subscription")
    s.add_argument("--days", type=int, help="duración (subscription/trial)")
    s.add_argument("--max-activations", type=int, default=1)
    s.add_argument("--features", help="lista separada por comas")
    s.add_argument("--notes")
    s.set_defaults(fn=cmd_create)

    s = sub.add_parser("list", help="lista licencias")
    s.add_argument("--product")
    s.add_argument("--status", choices=svc.STATUSES)
    s.add_argument("--limit", type=int, default=100)
    s.set_defaults(fn=cmd_list)

    s = sub.add_parser("show", help="detalle y activaciones")
    s.add_argument("id")
    s.set_defaults(fn=cmd_show)

    s = sub.add_parser("revoke", help="revoca (o con --undo reactiva)")
    s.add_argument("id")
    s.add_argument("--undo", action="store_true")
    s.set_defaults(fn=cmd_revoke)

    s = sub.add_parser("extend", help="renueva una suscripción")
    s.add_argument("id")
    s.add_argument("--days", type=int, required=True)
    s.set_defaults(fn=cmd_extend)

    s = sub.add_parser("release", help="libera activaciones")
    s.add_argument("id")
    s.add_argument("--fingerprint", help="solo esa; sin esto libera todas")
    s.set_defaults(fn=cmd_release)

    s = sub.add_parser("set-max", help="cambia el máximo de activaciones")
    s.add_argument("id")
    s.add_argument("n", type=int)
    s.set_defaults(fn=cmd_set_max)

    s = sub.add_parser("audit", help="bitácora de eventos")
    s.add_argument("--id")
    s.add_argument("--limit", type=int, default=30)
    s.set_defaults(fn=cmd_audit)

