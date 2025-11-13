"""add ended_at to sessions + indices

Revision ID: ba2c5f3a9bf8
Revises: e014f94bf8da
Create Date: 2025-11-10 12:25:57.259218
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'ba2c5f3a9bf8'
down_revision = 'e014f94bf8da'
branch_labels = None
depends_on = None


def upgrade():
    # --- Aggiungi colonna ended_at se non esiste già ---
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c['name'] for c in inspector.get_columns('sessions')]
    if 'ended_at' not in columns:
        op.add_column('sessions', sa.Column('ended_at', sa.DateTime(timezone=False), nullable=True))

    # --- Crea indici per performance KPI / admin ---
    existing_indexes = [ix['name'] for ix in inspector.get_indexes('sessions')]

    if 'ix_sessions_started_at' not in existing_indexes:
        op.create_index('ix_sessions_started_at', 'sessions', ['started_at'], unique=False)
    if 'ix_sessions_ended_at' not in existing_indexes:
        op.create_index('ix_sessions_ended_at', 'sessions', ['ended_at'], unique=False)
    if 'ix_sessions_is_active' not in existing_indexes:
        op.create_index('ix_sessions_is_active', 'sessions', ['is_active'], unique=False)


def downgrade():
    # --- Rimuovi indici e colonna ---
    with op.batch_alter_table('sessions') as batch_op:
        batch_op.drop_index('ix_sessions_is_active')
        batch_op.drop_index('ix_sessions_ended_at')
        batch_op.drop_index('ix_sessions_started_at')
        batch_op.drop_column('ended_at')
