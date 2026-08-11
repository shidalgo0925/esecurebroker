"""add documents table for client PDF attachments

Revision ID: a1b2c3d4e5f6
Revises: 700fc54b458f
Create Date: 2026-08-11
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "700fc54b458f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("party_id", sa.String(length=36), nullable=True),
        sa.Column("policy_id", sa.String(length=36), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=120), nullable=False),
        sa.Column("stored_name", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("doc_kind", sa.String(length=40), nullable=False),
        sa.Column("uploaded_by", sa.String(length=64), nullable=True),
        sa.Column("data_source", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["party_id"], ["parties.id"]),
        sa.ForeignKeyConstraint(["policy_id"], ["policies.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_documents_organization_id", "documents", ["organization_id"])
    op.create_index("ix_documents_party_id", "documents", ["party_id"])
    op.create_index("ix_documents_policy_id", "documents", ["policy_id"])


def downgrade() -> None:
    op.drop_index("ix_documents_policy_id", table_name="documents")
    op.drop_index("ix_documents_party_id", table_name="documents")
    op.drop_index("ix_documents_organization_id", table_name="documents")
    op.drop_table("documents")
