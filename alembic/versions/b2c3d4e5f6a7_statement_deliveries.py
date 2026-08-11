"""statement_deliveries for email / auto-send audit

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-08-11
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "statement_deliveries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("party_id", sa.String(length=36), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("trigger", sa.String(length=32), nullable=False),
        sa.Column("to_email", sa.String(length=200), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("overdue_balance", sa.Numeric(14, 2), nullable=False),
        sa.Column("open_balance", sa.Numeric(14, 2), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("actor_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["party_id"], ["parties.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_statement_deliveries_organization_id", "statement_deliveries", ["organization_id"])
    op.create_index("ix_statement_deliveries_party_id", "statement_deliveries", ["party_id"])


def downgrade() -> None:
    op.drop_index("ix_statement_deliveries_party_id", table_name="statement_deliveries")
    op.drop_index("ix_statement_deliveries_organization_id", table_name="statement_deliveries")
    op.drop_table("statement_deliveries")
