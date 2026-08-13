"""SaaS payment receipt verification queue

Revision ID: f0a1b2c3d4e5
Revises: e9f0a1b2c3d4
Create Date: 2026-08-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f0a1b2c3d4e5"
down_revision = "e9f0a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "saas_payment_receipts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("organization_id", sa.String(length=36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column(
            "subscription_id",
            sa.String(length=36),
            sa.ForeignKey("org_subscriptions.id"),
            nullable=True,
        ),
        sa.Column("plan_code", sa.String(length=40), nullable=False),
        sa.Column("method", sa.String(length=32), nullable=False),
        sa.Column("payment_reference", sa.String(length=120), nullable=True),
        sa.Column("amount_usd", sa.Integer(), nullable=True),
        sa.Column("relative_path", sa.String(length=500), nullable=False),
        sa.Column("original_filename", sa.String(length=200), nullable=False),
        sa.Column("content_type", sa.String(length=120), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reported_by", sa.String(length=200), nullable=True),
        sa.Column("verification_status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("reviewer_subject_id", sa.String(length=128), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_saas_payment_receipts_organization_id", "saas_payment_receipts", ["organization_id"])
    op.create_index("ix_saas_payment_receipts_subscription_id", "saas_payment_receipts", ["subscription_id"])
    op.create_index(
        "ix_saas_receipts_status_created",
        "saas_payment_receipts",
        ["verification_status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_saas_receipts_status_created", table_name="saas_payment_receipts")
    op.drop_index("ix_saas_payment_receipts_subscription_id", table_name="saas_payment_receipts")
    op.drop_index("ix_saas_payment_receipts_organization_id", table_name="saas_payment_receipts")
    op.drop_table("saas_payment_receipts")
