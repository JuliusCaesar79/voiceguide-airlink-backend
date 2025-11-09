"""add payload (JSONB) column to events

Revision ID: 0005_add_payload_to_events
Revises: 0004_add_license_code_to_events
Create Date: 2025-11-04 23:45:00
"""

from alembic import op
import sqlalchemy as sa


# Revision identifiers, used by Alembic.
revision = "0005_add_payload_to_events"
down_revision = "0004_add_license_code_to_events"
branch_labels = None
depends_on = None


def upgrade():
    # Aggiunge la colonna payload come JSONB solo se non esiste già
    op.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS payload JSONB")


def downgrade():
    # Rimuove la colonna se presente
    op.execute("ALTER TABLE events DROP COLUMN IF EXISTS payload")
