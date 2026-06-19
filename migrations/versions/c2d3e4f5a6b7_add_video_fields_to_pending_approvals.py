"""add video_url + video_style to pending_approvals

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-06-19 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'c2d3e4f5a6b7'
down_revision = 'b1c2d3e4f5a6'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('pending_approvals', schema=None) as batch_op:
        batch_op.add_column(sa.Column('video_url', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('video_style', sa.String(length=8), nullable=True))


def downgrade():
    with op.batch_alter_table('pending_approvals', schema=None) as batch_op:
        batch_op.drop_column('video_style')
        batch_op.drop_column('video_url')
