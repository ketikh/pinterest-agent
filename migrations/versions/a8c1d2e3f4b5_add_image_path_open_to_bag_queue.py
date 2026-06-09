"""add image_path_open to bag_queue (optional opened-bag photo)

Revision ID: a8c1d2e3f4b5
Revises: f54ccc0c063d
Create Date: 2026-05-25 14:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'a8c1d2e3f4b5'
down_revision = 'f54ccc0c063d'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('bag_queue', schema=None) as batch_op:
        batch_op.add_column(sa.Column('image_path_open', sa.String(length=512), nullable=True))


def downgrade():
    with op.batch_alter_table('bag_queue', schema=None) as batch_op:
        batch_op.drop_column('image_path_open')
