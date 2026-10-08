"""add household pantry config

Revision ID: f6a1b2c3d4e5
Revises: e5f9a0b1c2d3
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f6a1b2c3d4e5"
down_revision: Union[str, None] = "e5f9a0b1c2d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "household_pantry_configs",
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id"), primary_key=True),
        sa.Column("use_defaults", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("disabled_default_keys", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("custom_keys", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("household_pantry_configs")
