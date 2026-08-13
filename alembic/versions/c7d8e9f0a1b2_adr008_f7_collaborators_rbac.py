"""ADR-008 F7 — membership lifecycle, roles, invitations

Revision ID: c7d8e9f0a1b2
Revises: b1c2d3e4f5a6
Create Date: 2026-08-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c7d8e9f0a1b2"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("org_memberships", sa.Column("email", sa.String(length=200), nullable=True))
    op.add_column(
        "org_memberships",
        sa.Column("status", sa.String(length=32), nullable=False, server_default="ACTIVE"),
    )
    op.add_column(
        "org_memberships",
        sa.Column("producer_profile_id", sa.String(length=36), nullable=True),
    )
    op.add_column("org_memberships", sa.Column("invited_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "org_memberships", sa.Column("invited_by_subject_id", sa.String(length=128), nullable=True)
    )
    op.add_column("org_memberships", sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("org_memberships", sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "org_memberships", sa.Column("revoked_by_subject_id", sa.String(length=128), nullable=True)
    )
    op.add_column(
        "org_memberships", sa.Column("last_access_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index("ix_org_memberships_email", "org_memberships", ["email"])
    op.create_index("ix_org_memberships_status", "org_memberships", ["status"])
    op.create_index(
        "ix_org_memberships_producer_profile_id", "org_memberships", ["producer_profile_id"]
    )
    op.create_foreign_key(
        "fk_org_memberships_producer_profile_id",
        "org_memberships",
        "producer_profiles",
        ["producer_profile_id"],
        ["id"],
    )

    # Backfill status from active
    op.execute(
        sa.text(
            "UPDATE org_memberships SET status = CASE WHEN active THEN 'ACTIVE' ELSE 'INACTIVE' END"
        )
    )

    op.create_table(
        "org_roles",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("organization_id", sa.String(length=36), sa.ForeignKey("organizations.id"), nullable=True),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("system_role", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "default_scope", sa.String(length=32), nullable=False, server_default="ORGANIZATION"
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("organization_id", "code", name="uq_org_role_org_code"),
    )
    op.create_index("ix_org_roles_organization_id", "org_roles", ["organization_id"])
    op.create_index("ix_org_roles_system_code", "org_roles", ["code"])

    op.create_table(
        "org_role_permissions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("role_id", sa.String(length=36), sa.ForeignKey("org_roles.id"), nullable=False),
        sa.Column("permission_code", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("role_id", "permission_code", name="uq_org_role_permission"),
    )
    op.create_index("ix_org_role_permissions_role_id", "org_role_permissions", ["role_id"])

    op.create_table(
        "org_invitations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "organization_id", sa.String(length=36), sa.ForeignKey("organizations.id"), nullable=False
        ),
        sa.Column(
            "membership_id", sa.String(length=36), sa.ForeignKey("org_memberships.id"), nullable=False
        ),
        sa.Column("email", sa.String(length=200), nullable=False),
        sa.Column("role_code", sa.String(length=64), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="PENDING"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by_subject_id", sa.String(length=128), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("token_hash", name="uq_org_invitations_token_hash"),
    )
    op.create_index("ix_org_invitations_organization_id", "org_invitations", ["organization_id"])
    op.create_index("ix_org_invitations_membership_id", "org_invitations", ["membership_id"])
    op.create_index("ix_org_invitations_token_hash", "org_invitations", ["token_hash"])
    op.create_index("ix_org_invitations_org_email", "org_invitations", ["organization_id", "email"])


def downgrade() -> None:
    op.drop_table("org_invitations")
    op.drop_table("org_role_permissions")
    op.drop_table("org_roles")
    op.drop_constraint("fk_org_memberships_producer_profile_id", "org_memberships", type_="foreignkey")
    op.drop_index("ix_org_memberships_producer_profile_id", table_name="org_memberships")
    op.drop_index("ix_org_memberships_status", table_name="org_memberships")
    op.drop_index("ix_org_memberships_email", table_name="org_memberships")
    for col in (
        "last_access_at",
        "revoked_by_subject_id",
        "revoked_at",
        "accepted_at",
        "invited_by_subject_id",
        "invited_at",
        "producer_profile_id",
        "status",
        "email",
    ):
        op.drop_column("org_memberships", col)
