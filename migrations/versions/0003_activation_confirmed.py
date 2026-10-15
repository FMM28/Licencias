"""Activaciones en dos fases: columna confirmed_at (pendiente hasta que el SDK confirma).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-14
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("activations", sa.Column("confirmed_at", sa.DateTime(), nullable=True))
    # Las activaciones que ya existían se dan por confirmadas.
    op.execute("UPDATE activations SET confirmed_at = created_at WHERE active = 1")


def downgrade() -> None:
    op.drop_column("activations", "confirmed_at")
