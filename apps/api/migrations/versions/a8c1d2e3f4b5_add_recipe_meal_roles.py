"""add recipe meal roles

Revision ID: a8c1d2e3f4b5
Revises: f6a1b2c3d4e5
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a8c1d2e3f4b5"
down_revision: str | None = "f6a1b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "recipes",
        sa.Column("meal_role", sa.String(length=32), nullable=False, server_default=""),
    )
    op.add_column(
        "recipes",
        sa.Column("staple_type", sa.String(length=16), nullable=False, server_default="无"),
    )
    op.add_column(
        "recipes",
        sa.Column("protein_sources", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "recipes",
        sa.Column("vegetable_keys", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "recipes",
        sa.Column(
            "portion_confidence",
            sa.String(length=32),
            nullable=False,
            server_default="servings_only",
        ),
    )
    from app.services.recipe_taxonomy import backfill_recipe_classifications

    backfill_recipe_classifications(op.get_bind())


def downgrade() -> None:
    op.drop_column("recipes", "portion_confidence")
    op.drop_column("recipes", "vegetable_keys")
    op.drop_column("recipes", "protein_sources")
    op.drop_column("recipes", "staple_type")
    op.drop_column("recipes", "meal_role")
