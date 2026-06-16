"""add product_type to bag_queue (bag vs necklace)

Revision ID: b1c2d3e4f5a6
Revises: a8c1d2e3f4b5
Create Date: 2026-06-16 11:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'b1c2d3e4f5a6'
down_revision = 'a8c1d2e3f4b5'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('bag_queue', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('product_type', sa.String(length=32),
                      nullable=False, server_default='bag')
        )
        batch_op.create_index('ix_bag_queue_product_type', ['product_type'])


def downgrade():
    with op.batch_alter_table('bag_queue', schema=None) as batch_op:
        batch_op.drop_index('ix_bag_queue_product_type')
        batch_op.drop_column('product_type')
