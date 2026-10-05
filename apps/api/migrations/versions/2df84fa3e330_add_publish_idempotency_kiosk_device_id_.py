"""add publish idempotency, kiosk device_id, feedback idempotency

Revision ID: 2df84fa3e330
Revises: 4c4dc986866b
Create Date: 2026-10-05 17:48:55.099307

数据字典/接口契约（docs/api.md、docs/数据字典.md）：
- kiosk_devices.device_id：终端必填标识，明文令牌只展示一次
- meal_plans：发布幂等键（同键重放返回同一结果）、发布时间、约束快照
- feedback.idempotency_key：反馈幂等键，重放不产生重复记录
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '2df84fa3e330'
down_revision: Union[str, None] = '4c4dc986866b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('feedback', sa.Column('idempotency_key', sa.String(length=80), nullable=True))
    op.create_index(op.f('ix_feedback_idempotency_key'), 'feedback', ['idempotency_key'], unique=False)
    op.add_column('kiosk_devices', sa.Column('device_id', sa.String(length=80), nullable=False))
    op.create_index(op.f('ix_kiosk_devices_device_id'), 'kiosk_devices', ['device_id'], unique=True)
    op.add_column('meal_plans', sa.Column('constraints_snapshot', sa.JSON(), nullable=False))
    op.add_column('meal_plans', sa.Column('published_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('meal_plans', sa.Column('publish_idempotency_key', sa.String(length=80), nullable=True))
    with op.batch_alter_table('meal_plans') as batch_op:
        batch_op.create_unique_constraint(
            'uq_meal_plans_publish_idempotency_key', ['publish_idempotency_key']
        )


def downgrade() -> None:
    with op.batch_alter_table('meal_plans') as batch_op:
        batch_op.drop_constraint('uq_meal_plans_publish_idempotency_key', type_='unique')
    op.drop_column('meal_plans', 'publish_idempotency_key')
    op.drop_column('meal_plans', 'published_at')
    op.drop_column('meal_plans', 'constraints_snapshot')
    op.drop_index(op.f('ix_kiosk_devices_device_id'), table_name='kiosk_devices')
    op.drop_column('kiosk_devices', 'device_id')
    op.drop_index(op.f('ix_feedback_idempotency_key'), table_name='feedback')
    op.drop_column('feedback', 'idempotency_key')
