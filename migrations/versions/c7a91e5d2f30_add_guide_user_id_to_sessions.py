"""add guide_user_id to sessions (account Supabase della guida)

Revision ID: c7a91e5d2f30
Revises: 904be9dbea77
Create Date: 2026-11-18
"""

from alembic import op
import sqlalchemy as sa


revision = "c7a91e5d2f30"
down_revision = "904be9dbea77"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("sessions", sa.Column("guide_user_id", sa.String(length=36), nullable=True))


def downgrade():
    op.drop_column("sessions", "guide_user_id")
