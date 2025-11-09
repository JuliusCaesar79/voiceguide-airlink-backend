"""add event_logs table

Revision ID: 0006_add_event_logs
Revises: 0005_add_payload_to_events
Create Date: 2025-11-06 00:00:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# ------------------------------------------------------------
# REVISION IDENTIFIERS
# ------------------------------------------------------------
revision = "0006_add_event_logs"
down_revision = "0005_add_payload_to_events"
branch_labels = None
depends_on = None


def upgrade():
    # ✅ Crea (una sola volta) il tipo ENUM (idempotente)
    event_status = postgresql.ENUM("queued", "sent", "failed", name="event_status", create_type=False)
    event_status.create(op.get_bind(), checkfirst=True)

    # ✅ Tabella event_logs (la colonna usa lo stesso oggetto ENUM,
    #    ma con create_type=False NON tenterà di ricreare il tipo)
    op.create_table(
        "event_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),

        sa.Column("status", event_status, nullable=False, server_default="queued"),
        sa.Column("retries", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),

        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
    )

    op.create_index("ix_event_logs_event_type", "event_logs", ["event_type"], unique=False)


def downgrade():
    op.drop_index("ix_event_logs_event_type", table_name="event_logs")
    op.drop_table("event_logs")

    # ✅ Drop sicuro dell'ENUM (solo se non usato altrove)
    event_status = postgresql.ENUM("queued", "sent", "failed", name="event_status", create_type=False)
    event_status.drop(op.get_bind(), checkfirst=True)
