"""ADR-011 F1 — ESB CRM domain (prospects, opportunities, activities, catalogs)

Revision ID: a011f1c0ffee
Revises: f0a1b2c3d4e5
Create Date: 2026-08-13

DEV only for initial GO. Do not apply on PROD until explicit cutover.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a011f1c0ffee"
down_revision = "f0a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crm_lead_sources",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("organization_id", sa.String(length=36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("organization_id", "code", name="uq_crm_lead_source_org_code"),
    )
    op.create_index("ix_crm_lead_sources_organization_id", "crm_lead_sources", ["organization_id"])
    op.create_index("ix_crm_lead_sources_org", "crm_lead_sources", ["organization_id"])

    op.create_table(
        "crm_lost_reasons",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("organization_id", sa.String(length=36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("organization_id", "code", name="uq_crm_lost_reason_org_code"),
    )
    op.create_index("ix_crm_lost_reasons_organization_id", "crm_lost_reasons", ["organization_id"])
    op.create_index("ix_crm_lost_reasons_org", "crm_lost_reasons", ["organization_id"])

    op.create_table(
        "crm_pipeline_stages",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("organization_id", sa.String(length=36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("is_won", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_lost", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_kanban", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("organization_id", "code", name="uq_crm_pipeline_stage_org_code"),
        sa.UniqueConstraint("organization_id", "sequence", name="uq_crm_pipeline_stage_org_seq"),
    )
    op.create_index("ix_crm_pipeline_stages_organization_id", "crm_pipeline_stages", ["organization_id"])
    op.create_index("ix_crm_pipeline_stages_org", "crm_pipeline_stages", ["organization_id"])

    op.create_table(
        "crm_prospects",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("organization_id", sa.String(length=36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("prospect_type", sa.String(length=32), nullable=False, server_default="PERSON"),
        sa.Column("first_name", sa.String(length=120), nullable=True),
        sa.Column("last_name", sa.String(length=120), nullable=True),
        sa.Column("company_name", sa.String(length=200), nullable=True),
        sa.Column("identification_type", sa.String(length=40), nullable=True),
        sa.Column("identification_number", sa.String(length=64), nullable=True),
        sa.Column("phone", sa.String(length=40), nullable=True),
        sa.Column("mobile", sa.String(length=40), nullable=True),
        sa.Column("email", sa.String(length=200), nullable=True),
        sa.Column("source_id", sa.String(length=36), sa.ForeignKey("crm_lead_sources.id"), nullable=True),
        sa.Column("referral_source_id", sa.String(length=36), sa.ForeignKey("parties.id"), nullable=True),
        sa.Column(
            "assigned_producer_id",
            sa.String(length=36),
            sa.ForeignKey("producer_profiles.id"),
            nullable=True,
        ),
        sa.Column("assigned_executive_id", sa.String(length=128), nullable=True),
        sa.Column("office_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="OPEN"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=128), nullable=True),
        sa.Column(
            "converted_customer_id",
            sa.String(length=36),
            sa.ForeignKey("parties.id"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_crm_prospects_organization_id", "crm_prospects", ["organization_id"])
    op.create_index("ix_crm_prospects_org_status", "crm_prospects", ["organization_id", "status"])
    op.create_index("ix_crm_prospects_org_email", "crm_prospects", ["organization_id", "email"])
    op.create_index("ix_crm_prospects_org_phone", "crm_prospects", ["organization_id", "phone"])
    op.create_index("ix_crm_prospects_org_mobile", "crm_prospects", ["organization_id", "mobile"])
    op.create_index(
        "ix_crm_prospects_org_idnum", "crm_prospects", ["organization_id", "identification_number"]
    )
    op.create_index(
        "ix_crm_prospects_assigned_producer",
        "crm_prospects",
        ["organization_id", "assigned_producer_id"],
    )
    op.create_index("ix_crm_prospects_source_id", "crm_prospects", ["source_id"])
    op.create_index("ix_crm_prospects_referral_source_id", "crm_prospects", ["referral_source_id"])
    op.create_index("ix_crm_prospects_assigned_producer_id", "crm_prospects", ["assigned_producer_id"])
    op.create_index("ix_crm_prospects_office_id", "crm_prospects", ["office_id"])
    op.create_index("ix_crm_prospects_converted_customer_id", "crm_prospects", ["converted_customer_id"])

    op.create_table(
        "crm_opportunities",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("organization_id", sa.String(length=36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("prospect_id", sa.String(length=36), sa.ForeignKey("crm_prospects.id"), nullable=True),
        sa.Column("customer_id", sa.String(length=36), sa.ForeignKey("parties.id"), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column(
            "line_of_business_id",
            sa.String(length=36),
            sa.ForeignKey("insurance_lines.id"),
            nullable=True,
        ),
        sa.Column("product_interest", sa.String(length=200), nullable=True),
        sa.Column("carrier_id", sa.String(length=36), sa.ForeignKey("carriers.id"), nullable=True),
        sa.Column(
            "assigned_producer_id",
            sa.String(length=36),
            sa.ForeignKey("producer_profiles.id"),
            nullable=True,
        ),
        sa.Column("assigned_executive_id", sa.String(length=128), nullable=True),
        sa.Column("office_id", sa.String(length=36), nullable=True),
        sa.Column(
            "stage_id",
            sa.String(length=36),
            sa.ForeignKey("crm_pipeline_stages.id"),
            nullable=True,
        ),
        sa.Column("stage_code", sa.String(length=40), nullable=False, server_default="NEW"),
        sa.Column("estimated_premium", sa.Numeric(14, 2), nullable=True),
        sa.Column("probability", sa.Integer(), nullable=True),
        sa.Column("expected_close_date", sa.Date(), nullable=True),
        sa.Column("next_activity_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_id", sa.String(length=36), sa.ForeignKey("crm_lead_sources.id"), nullable=True),
        sa.Column("referral_source_id", sa.String(length=36), sa.ForeignKey("parties.id"), nullable=True),
        sa.Column(
            "lost_reason_id",
            sa.String(length=36),
            sa.ForeignKey("crm_lost_reasons.id"),
            nullable=True,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("won_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lost_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reopened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.CheckConstraint(
            "prospect_id IS NOT NULL OR customer_id IS NOT NULL",
            name="ck_crm_opp_prospect_or_customer",
        ),
    )
    op.create_index("ix_crm_opportunities_organization_id", "crm_opportunities", ["organization_id"])
    op.create_index("ix_crm_opp_org_stage", "crm_opportunities", ["organization_id", "stage_code"])
    op.create_index("ix_crm_opp_org_prospect", "crm_opportunities", ["organization_id", "prospect_id"])
    op.create_index("ix_crm_opp_org_customer", "crm_opportunities", ["organization_id", "customer_id"])
    op.create_index(
        "ix_crm_opp_assigned_producer",
        "crm_opportunities",
        ["organization_id", "assigned_producer_id"],
    )
    op.create_index(
        "ix_crm_opp_next_activity", "crm_opportunities", ["organization_id", "next_activity_at"]
    )
    for col in (
        "prospect_id",
        "customer_id",
        "line_of_business_id",
        "carrier_id",
        "assigned_producer_id",
        "office_id",
        "stage_id",
        "source_id",
        "referral_source_id",
        "lost_reason_id",
    ):
        op.create_index(f"ix_crm_opportunities_{col}", "crm_opportunities", [col])

    op.create_table(
        "crm_activities",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("organization_id", sa.String(length=36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column(
            "opportunity_id",
            sa.String(length=36),
            sa.ForeignKey("crm_opportunities.id"),
            nullable=True,
        ),
        sa.Column("prospect_id", sa.String(length=36), sa.ForeignKey("crm_prospects.id"), nullable=True),
        sa.Column("activity_type", sa.String(length=40), nullable=False, server_default="FOLLOW_UP"),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="PENDING"),
        sa.Column("result", sa.String(length=200), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("assignee_subject_id", sa.String(length=128), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_crm_activities_organization_id", "crm_activities", ["organization_id"])
    op.create_index("ix_crm_act_org_status", "crm_activities", ["organization_id", "status"])
    op.create_index("ix_crm_act_org_due", "crm_activities", ["organization_id", "due_at"])
    op.create_index("ix_crm_act_opportunity", "crm_activities", ["organization_id", "opportunity_id"])
    op.create_index("ix_crm_act_prospect", "crm_activities", ["organization_id", "prospect_id"])
    op.create_index("ix_crm_act_assignee", "crm_activities", ["organization_id", "assignee_subject_id"])
    op.create_index("ix_crm_activities_opportunity_id", "crm_activities", ["opportunity_id"])
    op.create_index("ix_crm_activities_prospect_id", "crm_activities", ["prospect_id"])


def downgrade() -> None:
    op.drop_table("crm_activities")
    op.drop_table("crm_opportunities")
    op.drop_table("crm_prospects")
    op.drop_table("crm_pipeline_stages")
    op.drop_table("crm_lost_reasons")
    op.drop_table("crm_lead_sources")
