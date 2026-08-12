"""ADR-008 F5 — org_subscriptions seat limit columns

Revision ID: a9b0c1d2e3f4
Revises: f8a901b2c3d4
Create Date: 2026-08-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a9b0c1d2e3f4"
down_revision = "f8a901b2c3d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "org_subscriptions",
        sa.Column("seats_limits_source", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "org_subscriptions",
        sa.Column("internal_seats_limit", sa.Integer(), nullable=True),
    )
    op.add_column(
        "org_subscriptions",
        sa.Column("producer_seats_limit", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("org_subscriptions", "producer_seats_limit")
    op.drop_column("org_subscriptions", "internal_seats_limit")
    op.drop_column("org_subscriptions", "seats_limits_source")
