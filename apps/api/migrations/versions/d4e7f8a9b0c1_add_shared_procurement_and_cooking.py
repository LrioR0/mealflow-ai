"""add shared procurement and cooking records

Revision ID: d4e7f8a9b0c1
Revises: c8d4e1f26a90
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4e7f8a9b0c1"
down_revision: Union[str, None] = "c8d4e1f26a90"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "procurement_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("ingredient", sa.String(length=120), nullable=False),
        sa.Column("quantity", sa.String(length=40), nullable=False),
        sa.Column("unit", sa.String(length=20), nullable=False),
        sa.Column("checked", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("source_id", sa.String(length=120), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_procurement_items_workspace_id", "procurement_items", ["workspace_id"])

    op.create_table(
        "cooking_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("dish_name", sa.String(length=120), nullable=False),
        sa.Column("cook", sa.String(length=80), nullable=False),
        sa.Column("cooked_at", sa.String(length=40), nullable=False),
        sa.Column("servings", sa.Integer(), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("difficulty", sa.String(length=20), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("ingredients", sa.Text(), nullable=False),
        sa.Column("story", sa.Text(), nullable=False),
        sa.Column("steps", sa.JSON(), nullable=False),
        sa.Column("rating", sa.Numeric(3, 1), nullable=False),
        sa.Column("next_time_note", sa.Text(), nullable=False),
        sa.Column("image", sa.Text(), nullable=False),
        sa.Column("reviews", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cooking_records_workspace_id", "cooking_records", ["workspace_id"])
    op.create_index("ix_cooking_records_dish_name", "cooking_records", ["dish_name"])


def downgrade() -> None:
    op.drop_index("ix_cooking_records_dish_name", table_name="cooking_records")
    op.drop_index("ix_cooking_records_workspace_id", table_name="cooking_records")
    op.drop_table("cooking_records")
    op.drop_index("ix_procurement_items_workspace_id", table_name="procurement_items")
    op.drop_table("procurement_items")
