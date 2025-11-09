"""Initial schema for VoiceGuide AirLink: licenses, sessions, listeners.

Revision ID: 0001_init
Revises: 
Create Date: 2025-11-04 13:20:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as psql

# revision identifiers, used by Alembic.
revision = "0001_init"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------------------------------------------
    # licenses
    # ---------------------------------------------
    op.create_table(
        "licenses",
        sa.Column("id", psql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False, server_default=sa.text("240")),  # 4h
        sa.Column("max_listeners", sa.Integer(), nullable=False, server_default=sa.text("10")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("activated_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("code", name="uq_licenses_code"),
        sa.CheckConstraint("max_listeners IN (10,25,35,100)", name="ck_license_max_listeners_allowed"),
    )
    op.create_index("ix_licenses_code", "licenses", ["code"], unique=False)

    # ---------------------------------------------
    # sessions
    # ---------------------------------------------
    op.create_table(
        "sessions",
        sa.Column("id", psql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("license_id", psql.UUID(as_uuid=True), nullable=False),
        sa.Column("pin", sa.String(length=6), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.text("now()")),
        sa.Column("expires_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("max_listeners", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.UniqueConstraint("pin", name="uq_sessions_pin"),
        sa.ForeignKeyConstraint(
            ["license_id"], ["licenses.id"], name="fk_sessions_license_id__licenses", ondelete="CASCADE"
        ),
    )
    op.create_index("ix_sessions_pin", "sessions", ["pin"], unique=False)

    # ---------------------------------------------
    # listeners
    # ---------------------------------------------
    op.create_table(
        "listeners",
        sa.Column("id", psql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("session_id", psql.UUID(as_uuid=True), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=True),
        sa.Column("joined_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["session_id"], ["sessions.id"], name="fk_listeners_session_id__sessions", ondelete="CASCADE"
        ),
    )
    op.create_index("ix_listeners_session_id", "listeners", ["session_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_listeners_session_id", table_name="listeners")
    op.drop_table("listeners")

    op.drop_index("ix_sessions_pin", table_name="sessions")
    op.drop_table("sessions")

    op.drop_index("ix_licenses_code", table_name="licenses")
    op.drop_table("licenses")
