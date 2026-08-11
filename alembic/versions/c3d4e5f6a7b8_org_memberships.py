"""statement_deliveries already present; add org_memberships (ADR-007)

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-08-11
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "org_memberships",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("subject_id", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=True),
        sa.Column("role_code", sa.String(length=64), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("external_en1_membership_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("subject_id", "organization_id", name="uq_org_membership_subject_org"),
        sa.UniqueConstraint("external_en1_membership_id"),
    )
    op.create_index("ix_org_memberships_organization_id", "org_memberships", ["organization_id"])
    op.create_index("ix_org_memberships_subject_id", "org_memberships", ["subject_id"])


def downgrade() -> None:
    op.drop_index("ix_org_memberships_subject_id", table_name="org_memberships")
    op.drop_index("ix_org_memberships_organization_id", table_name="org_memberships")
    op.drop_table("org_memberships")
