"""Public channel payment attempts.

Revision ID: e2f3a4b5c6d7
Revises: e1f2a3b4c5d6
Create Date: 2026-08-18

DEV first. Do not apply on PROD until explicit GO.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e2f3a4b5c6d7"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "public_payment_attempts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("quote_id", sa.String(36), sa.ForeignKey("public_quotes.id"), nullable=False),
        sa.Column(
            "organization_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False
        ),
        sa.Column(
            "channel_id", sa.String(36), sa.ForeignKey("public_sales_channels.id"), nullable=False
        ),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False, server_default="USD"),
        sa.Column("status", sa.String(32), nullable=False, server_default="CREATED"),
        sa.Column("provider", sa.String(32), nullable=False, server_default="SANDBOX"),
        sa.Column("provider_ref", sa.String(128)),
        sa.Column("idempotency_key", sa.String(80), nullable=False),
        sa.Column("redirect_url", sa.Text()),
        sa.Column("raw_event_json", sa.Text()),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("failure_reason", sa.String(240)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("idempotency_key", name="uq_public_payment_attempt_idem"),
    )
    op.create_index("ix_public_payment_attempts_quote_id", "public_payment_attempts", ["quote_id"])
    op.create_index("ix_public_payment_attempts_quote", "public_payment_attempts", ["quote_id"])
    op.create_index(
        "ix_public_payment_attempts_organization_id", "public_payment_attempts", ["organization_id"]
    )
    op.create_index(
        "ix_public_payment_attempts_channel_id", "public_payment_attempts", ["channel_id"]
    )
    op.create_index(
        "ix_public_payment_attempts_provider_ref", "public_payment_attempts", ["provider_ref"]
    )


def downgrade() -> None:
    op.drop_table("public_payment_attempts")
