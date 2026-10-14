"""Esquema inicial: licencias, activaciones y bitácora.

Si ya tenías una base creada con la versión anterior del proyecto (que usaba create_all),
marca esta revisión como aplicada y luego actualiza:
    python -m app.cli db stamp 0001
    python -m app.cli db upgrade

Revision ID: 0001
Revises:
Create Date: 2026-10-12
"""
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# Ambos prefijos: el dialecto "mariadb" ignora `mysql_*` (ver app/db/base.py).
MYSQL = {f"{dialect}_{name}": value for dialect in ("mysql", "mariadb")
         for name, value in {"engine": "InnoDB", "charset": "utf8mb4",
                             "collate": "utf8mb4_unicode_ci"}.items()}


def upgrade() -> None:
    op.create_table(
        "licenses",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("product", sa.String(64), nullable=False),
        sa.Column("customer", sa.String(200), nullable=False),
        sa.Column("email", sa.String(200), nullable=True),
        sa.Column("plan", sa.String(20), nullable=False),
        sa.Column("features", sa.JSON(), nullable=False),
        sa.Column("max_activations", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("revoked", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_licenses")),
        **MYSQL,
    )
    op.create_index(op.f("ix_licenses_key_hash"), "licenses", ["key_hash"], unique=True)
    op.create_index(op.f("ix_licenses_product"), "licenses", ["product"])

    op.create_table(
        "activations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("license_id", sa.String(32), nullable=False),
        sa.Column("fingerprint", sa.String(128), nullable=False),
        sa.Column("hostname", sa.String(200), nullable=True),
        sa.Column("first_ip", sa.String(64), nullable=True),
        sa.Column("last_ip", sa.String(64), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["license_id"], ["licenses.id"],
                                name=op.f("fk_activations_license_id_licenses")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_activations")),
        sa.UniqueConstraint("license_id", "fingerprint",
                            name="uq_activations_license_fingerprint"),
        **MYSQL,
    )
    op.create_index(op.f("ix_activations_license_id"), "activations", ["license_id"])

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("ts", sa.DateTime(), nullable=False),
        sa.Column("license_id", sa.String(32), nullable=True),
        sa.Column("event", sa.String(40), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("ip", sa.String(64), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
        **MYSQL,
    )
    op.create_index(op.f("ix_audit_log_ts"), "audit_log", ["ts"])
    op.create_index(op.f("ix_audit_log_license_id"), "audit_log", ["license_id"])


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("activations")
    op.drop_table("licenses")
