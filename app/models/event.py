# app/models/events.py
from sqlalchemy import Column, String, DateTime, ForeignKey, Text, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func

from app.db.base import Base


class Event(Base):
    __tablename__ = "events"

    # Core
    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    type = Column(String(64), nullable=False)  # es: license_activated, session_started, listener_joined, session_ended
    description = Column(Text, nullable=True)

    # Relazioni/chiavi leggere
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True)
    license_code = Column(String(64), nullable=True, index=True)  # non FK hard per compatibilità retro

    # Dati evento (per Step 1 leggiamo: payload->>'listeners_count' per session_ended)
    payload = Column(JSONB, nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Indici compositi utili per stats/export
    __table_args__ = (
        Index("ix_events_type_created_at", "type", "created_at"),
        Index("ix_events_session_id_created_at", "session_id", "created_at"),
        Index("ix_events_license_code_created_at", "license_code", "created_at"),
    )
