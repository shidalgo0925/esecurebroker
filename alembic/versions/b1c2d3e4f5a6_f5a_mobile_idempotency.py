"""F5A — client_upload_id / client_activity_id for mobile idempotency

Revision ID: b1c2d3e4f5a6
Revises: a9b0c1d2e3f4
Create Date: 2026-08-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b1c2d3e4f5a6"
down_revision = "a9b0c1d2e3f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("client_upload_id", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("content_sha256", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_documents_client_upload_id",
        "documents",
        ["client_upload_id"],
        unique=False,
    )
    op.create_index(
        "uq_documents_org_client_upload",
        "documents",
        ["organization_id", "client_upload_id"],
        unique=True,
        postgresql_where=sa.text("client_upload_id IS NOT NULL"),
        sqlite_where=sa.text("client_upload_id IS NOT NULL"),
    )

    op.add_column(
        "interactions",
        sa.Column("client_activity_id", sa.String(length=128), nullable=True),
    )
    op.create_index(
        "ix_interactions_client_activity_id",
        "interactions",
        ["client_activity_id"],
        unique=False,
    )
    op.create_index(
        "uq_interactions_org_client_activity",
        "interactions",
        ["organization_id", "client_activity_id"],
        unique=True,
        postgresql_where=sa.text("client_activity_id IS NOT NULL"),
        sqlite_where=sa.text("client_activity_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_interactions_org_client_activity", table_name="interactions")
    op.drop_index("ix_interactions_client_activity_id", table_name="interactions")
    op.drop_column("interactions", "client_activity_id")
    op.drop_index("uq_documents_org_client_upload", table_name="documents")
    op.drop_index("ix_documents_client_upload_id", table_name="documents")
    op.drop_column("documents", "content_sha256")
    op.drop_column("documents", "client_upload_id")
