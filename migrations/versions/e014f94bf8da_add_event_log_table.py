"""add event_log table

Revision ID: e014f94bf8da
Revises: 0006_add_event_logs
Create Date: 2025-11-08 10:25:15.228253
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'e014f94bf8da'
down_revision = '0006_add_event_logs'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "event_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("listener_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'received'"), nullable=False),
    )

    op.create_index("ix_event_log_created_at", "event_log", ["created_at"])
    op.create_index("ix_event_log_type", "event_log", ["type"])
    op.create_index("ix_event_log_session_id", "event_log", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_event_log_session_id", table_name="event_log")
    op.drop_index("ix_event_log_type", table_name="event_log")
    op.drop_index("ix_event_log_created_at", table_name="event_log")
    op.drop_table("event_log")
