"""ADR-009 — Carrier Incentive Plans schema

Revision ID: d8e9f0a1b2c3
Revises: c7d8e9f0a1b2
Create Date: 2026-08-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d8e9f0a1b2c3"
down_revision = "c7d8e9f0a1b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "carrier_incentive_plans",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("organization_id", sa.String(length=36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("carrier_id", sa.String(length=36), sa.ForeignKey("carriers.id"), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("metric_type", sa.String(length=32), nullable=False),
        sa.Column("period_type", sa.String(length=32), nullable=False, server_default="CUSTOM"),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="USD"),
        sa.Column("calculation_base", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="DRAFT"),
        sa.Column("conditions_locked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_carrier_incentive_plans_organization_id", "carrier_incentive_plans", ["organization_id"])
    op.create_index("ix_carrier_incentive_plans_carrier_id", "carrier_incentive_plans", ["carrier_id"])
    op.create_index("ix_cip_org_carrier", "carrier_incentive_plans", ["organization_id", "carrier_id"])
    op.create_index("ix_cip_org_status", "carrier_incentive_plans", ["organization_id", "status"])

    op.create_table(
        "carrier_incentive_scopes",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("organization_id", sa.String(length=36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("plan_id", sa.String(length=36), sa.ForeignKey("carrier_incentive_plans.id"), nullable=False),
        sa.Column("scope_kind", sa.String(length=32), nullable=False),
        sa.Column("insurance_line_id", sa.String(length=36), sa.ForeignKey("insurance_lines.id"), nullable=True),
        sa.Column("carrier_product_id", sa.String(length=36), sa.ForeignKey("carrier_products.id"), nullable=True),
        sa.Column("agent_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint(
            "plan_id",
            "scope_kind",
            "insurance_line_id",
            "carrier_product_id",
            "agent_code",
            name="uq_cis_plan_scope_target",
        ),
    )
    op.create_index("ix_carrier_incentive_scopes_organization_id", "carrier_incentive_scopes", ["organization_id"])
    op.create_index("ix_cis_plan", "carrier_incentive_scopes", ["plan_id"])

    op.create_table(
        "carrier_incentive_tiers",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("organization_id", sa.String(length=36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("plan_id", sa.String(length=36), sa.ForeignKey("carrier_incentive_plans.id"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("threshold_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("benefit_type", sa.String(length=32), nullable=False),
        sa.Column("benefit_value", sa.Numeric(14, 4), nullable=False),
        sa.Column("calculation_base", sa.String(length=40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("plan_id", "sequence", name="uq_cit_plan_sequence"),
    )
    op.create_index("ix_carrier_incentive_tiers_organization_id", "carrier_incentive_tiers", ["organization_id"])
    op.create_index("ix_cit_plan", "carrier_incentive_tiers", ["plan_id"])

    op.create_table(
        "carrier_incentive_eligible_txns",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("organization_id", sa.String(length=36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("plan_id", sa.String(length=36), sa.ForeignKey("carrier_incentive_plans.id"), nullable=False),
        sa.Column("policy_id", sa.String(length=36), sa.ForeignKey("policies.id"), nullable=True),
        sa.Column("payment_id", sa.String(length=36), sa.ForeignKey("payments.id"), nullable=True),
        sa.Column("insurance_line_id", sa.String(length=36), sa.ForeignKey("insurance_lines.id"), nullable=True),
        sa.Column("carrier_id", sa.String(length=36), sa.ForeignKey("carriers.id"), nullable=False),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("txn_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="USD"),
        sa.Column("agent_code", sa.String(length=64), nullable=True),
        sa.Column("carrier_receipt_number", sa.String(length=120), nullable=True),
        sa.Column("confirmation_status", sa.String(length=32), nullable=False, server_default="PENDING"),
        sa.Column("reversed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reverse_reason", sa.String(length=500), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("plan_id", "source_type", "source_id", name="uq_cie_plan_source"),
    )
    op.create_index(
        "ix_carrier_incentive_eligible_txns_organization_id",
        "carrier_incentive_eligible_txns",
        ["organization_id"],
    )
    op.create_index("ix_cie_plan_status", "carrier_incentive_eligible_txns", ["plan_id", "confirmation_status"])
    op.create_index("ix_cie_org_policy", "carrier_incentive_eligible_txns", ["organization_id", "policy_id"])

    op.create_table(
        "carrier_incentive_settlements",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("organization_id", sa.String(length=36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("plan_id", sa.String(length=36), sa.ForeignKey("carrier_incentive_plans.id"), nullable=False),
        sa.Column("period_label", sa.String(length=80), nullable=False),
        sa.Column("eligible_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("calculated_benefit", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("benefit_stage", sa.String(length=32), nullable=False, server_default="ESTIMATED"),
        sa.Column("claimed_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recognized_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("recognized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="CALCULATED"),
        sa.Column("carrier_reference", sa.String(length=120), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("closed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("plan_id", "period_label", name="uq_ciset_plan_period"),
    )
    op.create_index(
        "ix_carrier_incentive_settlements_organization_id",
        "carrier_incentive_settlements",
        ["organization_id"],
    )
    op.create_index("ix_ciset_plan_status", "carrier_incentive_settlements", ["plan_id", "status"])

    op.create_table(
        "carrier_incentive_evidence",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("organization_id", sa.String(length=36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("plan_id", sa.String(length=36), sa.ForeignKey("carrier_incentive_plans.id"), nullable=False),
        sa.Column(
            "settlement_id",
            sa.String(length=36),
            sa.ForeignKey("carrier_incentive_settlements.id"),
            nullable=True,
        ),
        sa.Column("document_id", sa.String(length=36), sa.ForeignKey("documents.id"), nullable=True),
        sa.Column("evidence_kind", sa.String(length=40), nullable=False, server_default="OTRO"),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("stored_path", sa.String(length=500), nullable=True),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("uploaded_by", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_carrier_incentive_evidence_organization_id",
        "carrier_incentive_evidence",
        ["organization_id"],
    )
    op.create_index("ix_ciev_plan", "carrier_incentive_evidence", ["plan_id"])


def downgrade() -> None:
    op.drop_table("carrier_incentive_evidence")
    op.drop_table("carrier_incentive_settlements")
    op.drop_table("carrier_incentive_eligible_txns")
    op.drop_table("carrier_incentive_tiers")
    op.drop_table("carrier_incentive_scopes")
    op.drop_table("carrier_incentive_plans")
