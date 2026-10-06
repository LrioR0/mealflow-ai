"""member profile fields

人员信息档案库:users 加性别/常驻访客/忌口/备注字段。

Revision ID: c8d4e1f26a90
Revises: a7f3c2d91e44
Create Date: 2026-10-07
"""

from alembic import op
import sqlalchemy as sa

revision = "c8d4e1f26a90"
down_revision = "a7f3c2d91e44"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("gender", sa.String(10), nullable=True))
        batch_op.add_column(
            sa.Column("residency", sa.String(10), nullable=False, server_default="resident")
        )
        batch_op.add_column(sa.Column("taboo", sa.String(200), nullable=True))
        batch_op.add_column(sa.Column("note", sa.String(300), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("note")
        batch_op.drop_column("taboo")
        batch_op.drop_column("residency")
        batch_op.drop_column("gender")
