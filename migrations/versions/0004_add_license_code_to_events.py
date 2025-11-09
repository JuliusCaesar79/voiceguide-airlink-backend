"""add license_code column to events table

Revision ID: 0004_add_license_code_to_events
Revises: 0002_events
Create Date: 2025-11-04 20:00:00

"""
from alembic import op
import sqlalchemy as sa


# Revision identifiers, used by Alembic.
revision = '0004_add_license_code_to_events'
down_revision = '0002_events'  # ⚠️ sostituisci con l’ID effettivo dell’ultima migrazione
branch_labels = None
depends_on = None


def upgrade():
    """Aggiunge la colonna license_code alla tabella events."""
    with op.batch_alter_table('events', schema=None) as batch_op:
        batch_op.add_column(sa.Column('license_code', sa.String(length=64), nullable=True))


def downgrade():
    """Rimuove la colonna license_code dalla tabella events."""
    with op.batch_alter_table('events', schema=None) as batch_op:
        batch_op.drop_column('license_code')
