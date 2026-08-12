"""ADR-008 F1 — producer_profiles, portfolio_assignments, parties.default_producer

Revision ID: f8a901b2c3d4
Revises: e5f6a7b8c9d0
Create Date: 2026-08-12

Additive / reversible. No data destruction. Legacy orgs keep working without producers.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f8a901b2c3d4"
down_revision: Union[str, Sequence[str], None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "producer_profiles",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("party_id", sa.String(length=36), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=True),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["party_id"], ["parties.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "code", name="uq_producer_profile_org_code"),
        sa.UniqueConstraint("organization_id", "party_id", name="uq_producer_profile_org_party"),
    )
    op.create_index("ix_producer_profiles_organization_id", "producer_profiles", ["organization_id"])
    op.create_index("ix_producer_profiles_party_id", "producer_profiles", ["party_id"])

    op.create_table(
        "portfolio_assignments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("producer_profile_id", sa.String(length=36), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.String(length=36), nullable=False),
        sa.Column("assignment_role", sa.String(length=32), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("assigned_by_subject_id", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["producer_profile_id"], ["producer_profiles.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_portfolio_assignments_organization_id", "portfolio_assignments", ["organization_id"]
    )
    op.create_index(
        "ix_portfolio_assignments_producer_profile_id",
        "portfolio_assignments",
        ["producer_profile_id"],
    )
    op.create_index(
        "ix_portfolio_assignments_producer",
        "portfolio_assignments",
        ["organization_id", "producer_profile_id"],
    )
    op.create_index(
        "ix_portfolio_assignments_target",
        "portfolio_assignments",
        ["organization_id", "target_type", "target_id"],
    )
    # One active PRIMARY per policy (PostgreSQL / SQLite partial unique)
    op.create_index(
        "uq_portfolio_primary_policy_active",
        "portfolio_assignments",
        ["organization_id", "target_id"],
        unique=True,
        postgresql_where=sa.text(
            "target_type = 'POLICY' AND assignment_role = 'PRIMARY' AND effective_to IS NULL"
        ),
        sqlite_where=sa.text(
            "target_type = 'POLICY' AND assignment_role = 'PRIMARY' AND effective_to IS NULL"
        ),
    )

    op.add_column(
        "parties",
        sa.Column("default_producer_profile_id", sa.String(length=36), nullable=True),
    )
    op.create_index(
        "ix_parties_default_producer_profile_id",
        "parties",
        ["default_producer_profile_id"],
    )
    op.create_foreign_key(
        "fk_parties_default_producer_profile_id",
        "parties",
        "producer_profiles",
        ["default_producer_profile_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_parties_default_producer_profile_id", "parties", type_="foreignkey")
    op.drop_index("ix_parties_default_producer_profile_id", table_name="parties")
    op.drop_column("parties", "default_producer_profile_id")

    op.drop_index("uq_portfolio_primary_policy_active", table_name="portfolio_assignments")
    op.drop_index("ix_portfolio_assignments_target", table_name="portfolio_assignments")
    op.drop_index("ix_portfolio_assignments_producer", table_name="portfolio_assignments")
    op.drop_index("ix_portfolio_assignments_producer_profile_id", table_name="portfolio_assignments")
    op.drop_index("ix_portfolio_assignments_organization_id", table_name="portfolio_assignments")
    op.drop_table("portfolio_assignments")

    op.drop_index("ix_producer_profiles_party_id", table_name="producer_profiles")
    op.drop_index("ix_producer_profiles_organization_id", table_name="producer_profiles")
    op.drop_table("producer_profiles")
