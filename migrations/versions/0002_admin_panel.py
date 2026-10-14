"""Panel de administración: usuarios, sesiones y autor de cada cambio en la bitácora.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-12
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

# Ambos prefijos: el dialecto "mariadb" ignora `mysql_*` (ver app/db/base.py).
MYSQL = {f"{dialect}_{name}": value for dialect in ("mysql", "mariadb")
         for name, value in {"engine": "InnoDB", "charset": "utf8mb4",
                             "collate": "utf8mb4_unicode_ci"}.items()}


def upgrade() -> None:
    op.create_table(
        "admin_users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("must_change_password", sa.Boolean(), nullable=False),
        sa.Column("failed_attempts", sa.Integer(), nullable=False),
        sa.Column("locked_until", sa.DateTime(), nullable=True),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
        sa.Column("password_changed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admin_users")),
        **MYSQL,
    )
    op.create_index(op.f("ix_admin_users_username"), "admin_users", ["username"], unique=True)

    op.create_table(
        "admin_sessions",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("csrf_token", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("ip", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.String(255), nullable=True),
        sa.Column("flash", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["admin_users.id"], ondelete="CASCADE",
                                name=op.f("fk_admin_sessions_user_id_admin_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admin_sessions")),
        **MYSQL,
    )
    op.create_index(op.f("ix_admin_sessions_user_id"), "admin_sessions", ["user_id"])
    op.create_index(op.f("ix_admin_sessions_expires_at"), "admin_sessions", ["expires_at"])

    op.add_column("audit_log", sa.Column("actor", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("audit_log", "actor")
    op.drop_table("admin_sessions")
    op.drop_table("admin_users")
