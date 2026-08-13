"""Organization identity / branding for PDF reports

Revision ID: e9f0a1b2c3d4
Revises: d8e9f0a1b2c3
Create Date: 2026-08-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e9f0a1b2c3d4"
down_revision = "d8e9f0a1b2c3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("organizations", sa.Column("legal_name", sa.String(length=200), nullable=True))
    op.add_column("organizations", sa.Column("trade_name", sa.String(length=200), nullable=True))
    op.add_column("organizations", sa.Column("tax_id", sa.String(length=64), nullable=True))
    op.add_column("organizations", sa.Column("phone", sa.String(length=40), nullable=True))
    op.add_column("organizations", sa.Column("email", sa.String(length=200), nullable=True))
    op.add_column("organizations", sa.Column("website", sa.String(length=200), nullable=True))
    op.add_column("organizations", sa.Column("address", sa.Text(), nullable=True))
    op.add_column("organizations", sa.Column("slogan", sa.String(length=240), nullable=True))
    op.add_column("organizations", sa.Column("document_footer", sa.String(length=500), nullable=True))
    op.add_column("organizations", sa.Column("logo_relpath", sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column("organizations", "logo_relpath")
    op.drop_column("organizations", "document_footer")
    op.drop_column("organizations", "slogan")
    op.drop_column("organizations", "address")
    op.drop_column("organizations", "website")
    op.drop_column("organizations", "email")
    op.drop_column("organizations", "phone")
    op.drop_column("organizations", "tax_id")
    op.drop_column("organizations", "trade_name")
    op.drop_column("organizations", "legal_name")
