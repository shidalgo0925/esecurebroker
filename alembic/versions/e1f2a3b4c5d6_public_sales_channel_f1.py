"""Public sales channel F1 — anonymous quote domain.

Revision ID: e1f2a3b4c5d6
Revises: a011f1c0ffee
Create Date: 2026-08-18

DEV only. Do not apply on PROD until explicit GO.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e1f2a3b4c5d6"
down_revision = "a011f1c0ffee"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "public_sales_channels",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("slug", sa.String(80), nullable=False),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("product_code", sa.String(40), nullable=False, server_default="VIAJE"),
        sa.Column("product_label", sa.String(200), nullable=False, server_default="Seguro de viaje"),
        sa.Column("origin_default", sa.String(120)),
        sa.Column("origin_fixed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("default_producer_profile_id", sa.String(36)),
        sa.Column("lead_source_id", sa.String(36), sa.ForeignKey("crm_lead_sources.id")),
        sa.Column("currency", sa.String(8), nullable=False, server_default="USD"),
        sa.Column("branding_json", sa.Text()),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("slug", name="uq_public_sales_channel_slug"),
    )
    op.create_index("ix_public_sales_channels_slug", "public_sales_channels", ["slug"])
    op.create_index("ix_public_sales_channels_organization_id", "public_sales_channels", ["organization_id"])
    op.create_index(
        "ix_public_sales_channels_default_producer_profile_id",
        "public_sales_channels",
        ["default_producer_profile_id"],
    )
    op.create_index("ix_public_sales_channels_lead_source_id", "public_sales_channels", ["lead_source_id"])

    op.create_table(
        "public_product_plans",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("channel_id", sa.String(36), sa.ForeignKey("public_sales_channels.id"), nullable=False),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("currency", sa.String(8), nullable=False, server_default="USD"),
        sa.Column("coverages_json", sa.Text()),
        sa.Column("limits_json", sa.Text()),
        sa.Column("highlight", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("channel_id", "code", name="uq_public_product_plan_channel_code"),
    )
    op.create_index("ix_public_product_plans_channel_id", "public_product_plans", ["channel_id"])
    op.create_index("ix_public_product_plans_channel", "public_product_plans", ["channel_id"])

    op.create_table(
        "public_plan_rates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("plan_id", sa.String(36), sa.ForeignKey("public_product_plans.id"), nullable=False),
        sa.Column("destination_region", sa.String(40), nullable=False),
        sa.Column("age_min", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("age_max", sa.Integer(), nullable=False, server_default="120"),
        sa.Column("amount_per_passenger_per_day", sa.Numeric(14, 4), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False, server_default="USD"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("notes", sa.String(200)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_public_plan_rates_plan_id", "public_plan_rates", ["plan_id"])
    op.create_index(
        "ix_public_plan_rates_plan_region",
        "public_plan_rates",
        ["plan_id", "destination_region"],
    )

    op.create_table(
        "public_quotes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("public_token", sa.String(64), nullable=False),
        sa.Column("channel_id", sa.String(36), sa.ForeignKey("public_sales_channels.id"), nullable=False),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="STARTED"),
        sa.Column("origin", sa.String(120)),
        sa.Column("destination", sa.String(200)),
        sa.Column("destination_region", sa.String(40)),
        sa.Column("start_date", sa.Date()),
        sa.Column("end_date", sa.Date()),
        sa.Column("days", sa.Integer()),
        sa.Column("passenger_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("ages_json", sa.Text()),
        sa.Column("quoted_plans_json", sa.Text()),
        sa.Column("selected_plan_code", sa.String(40)),
        sa.Column("selected_plan_snapshot_json", sa.Text()),
        sa.Column("currency", sa.String(8), nullable=False, server_default="USD"),
        sa.Column("selected_premium", sa.Numeric(14, 2)),
        sa.Column("crm_prospect_id", sa.String(36), sa.ForeignKey("crm_prospects.id")),
        sa.Column("crm_opportunity_id", sa.String(36), sa.ForeignKey("crm_opportunities.id")),
        sa.Column("checkout_ref", sa.String(120)),
        sa.Column("payment_status", sa.String(32)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("quoted_at", sa.DateTime(timezone=True)),
        sa.Column("selected_at", sa.DateTime(timezone=True)),
        sa.Column("paid_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("public_token", name="uq_public_quote_token"),
    )
    op.create_index("ix_public_quotes_public_token", "public_quotes", ["public_token"])
    op.create_index("ix_public_quotes_channel_id", "public_quotes", ["channel_id"])
    op.create_index("ix_public_quotes_organization_id", "public_quotes", ["organization_id"])
    op.create_index("ix_public_quotes_channel_status", "public_quotes", ["channel_id", "status"])
    op.create_index("ix_public_quotes_org_status", "public_quotes", ["organization_id", "status"])
    op.create_index("ix_public_quotes_crm_prospect_id", "public_quotes", ["crm_prospect_id"])
    op.create_index("ix_public_quotes_crm_opportunity_id", "public_quotes", ["crm_opportunity_id"])

    op.create_table(
        "public_quote_travelers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("quote_id", sa.String(36), sa.ForeignKey("public_quotes.id"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("first_name", sa.String(120)),
        sa.Column("last_name", sa.String(120)),
        sa.Column("birth_date", sa.Date()),
        sa.Column("age", sa.Integer()),
        sa.Column("identification_number", sa.String(64)),
        sa.Column("email", sa.String(200)),
        sa.Column("phone", sa.String(40)),
        sa.Column("is_pep", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("quote_id", "seq", name="uq_public_quote_traveler_seq"),
    )
    op.create_index("ix_public_quote_travelers_quote_id", "public_quote_travelers", ["quote_id"])
    op.create_index("ix_public_quote_travelers_quote", "public_quote_travelers", ["quote_id"])

    op.create_table(
        "public_quote_beneficiaries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "traveler_id",
            sa.String(36),
            sa.ForeignKey("public_quote_travelers.id"),
            nullable=False,
        ),
        sa.Column("seq", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("relationship", sa.String(80)),
        sa.Column("identification_number", sa.String(64)),
        sa.Column("phone", sa.String(40)),
        sa.Column("share_pct", sa.Numeric(5, 2)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("traveler_id", "seq", name="uq_public_quote_beneficiary_seq"),
    )
    op.create_index(
        "ix_public_quote_beneficiaries_traveler_id",
        "public_quote_beneficiaries",
        ["traveler_id"],
    )
    op.create_index(
        "ix_public_quote_beneficiaries_traveler",
        "public_quote_beneficiaries",
        ["traveler_id"],
    )

    op.create_table(
        "public_quote_emergency_contacts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("quote_id", sa.String(36), sa.ForeignKey("public_quotes.id"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("phone", sa.String(40), nullable=False),
        sa.Column("email", sa.String(200)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("quote_id", name="uq_public_quote_emergency"),
    )
    op.create_index(
        "ix_public_quote_emergency_contacts_quote_id",
        "public_quote_emergency_contacts",
        ["quote_id"],
    )


def downgrade() -> None:
    op.drop_table("public_quote_emergency_contacts")
    op.drop_table("public_quote_beneficiaries")
    op.drop_table("public_quote_travelers")
    op.drop_table("public_quotes")
    op.drop_table("public_plan_rates")
    op.drop_table("public_product_plans")
    op.drop_table("public_sales_channels")
