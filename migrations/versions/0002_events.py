"""events log

Revision ID: 0002_events
Revises: 0001_init
Create Date: 2025-11-04 00:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '0002_events'
down_revision = '0001_init'
branch_labels = None
depends_on = None

def upgrade():
    op.execute('CREATE EXTENSION IF NOT EXISTS pgcrypto;')
    op.create_table(
        'events',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), primary_key=True),
        sa.Column('type', sa.String(length=64), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('session_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('sessions.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False)
    )
    op.create_index('ix_events_created_at', 'events', ['created_at'], unique=False)

def downgrade():
    op.drop_index('ix_events_created_at', table_name='events')
    op.drop_table('events')
