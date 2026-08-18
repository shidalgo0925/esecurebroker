"""Public quote → Party + Policy links (ESB cartera).

Revision ID: e3f4a5b6c7d8
Revises: e2f3a4b5c6d7
Create Date: 2026-08-18

DEV first. Do not apply on PROD until explicit GO.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e3f4a5b6c7d8"
down_revision = "e2f3a4b5c6d7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "public_quotes",
        sa.Column("party_id", sa.String(36), sa.ForeignKey("parties.id"), nullable=True),
    )
    op.add_column(
        "public_quotes",
        sa.Column("policy_id", sa.String(36), sa.ForeignKey("policies.id"), nullable=True),
    )
    op.create_index("ix_public_quotes_party_id", "public_quotes", ["party_id"])
    op.create_index("ix_public_quotes_policy_id", "public_quotes", ["policy_id"])


def downgrade() -> None:
    op.drop_index("ix_public_quotes_policy_id", table_name="public_quotes")
    op.drop_index("ix_public_quotes_party_id", table_name="public_quotes")
    op.drop_column("public_quotes", "policy_id")
    op.drop_column("public_quotes", "party_id")
