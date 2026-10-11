"""add member food preferences

Revision ID: b9d2e3f4a5b6
Revises: a8c1d2e3f4b5
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b9d2e3f4a5b6"
down_revision: str | None = "a8c1d2e3f4b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "member_food_preferences",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("target_type", sa.String(length=16), nullable=False),
        sa.Column("target_key", sa.String(length=160), nullable=False),
        sa.Column("target_name", sa.String(length=160), nullable=False),
        sa.Column("preference", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "user_id",
            "target_type",
            "target_key",
            name="uq_member_food_preference_target",
        ),
    )
    op.create_index(
        op.f("ix_member_food_preferences_workspace_id"),
        "member_food_preferences",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_member_food_preferences_user_id"),
        "member_food_preferences",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_member_food_preferences_user_id"),
        table_name="member_food_preferences",
    )
    op.drop_index(
        op.f("ix_member_food_preferences_workspace_id"),
        table_name="member_food_preferences",
    )
    op.drop_table("member_food_preferences")
