import uuid
import enum
from sqlalchemy import Column, Text, DateTime, text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.db.base import Base

class EventStatus(str, enum.Enum):
    received = "received"
    sent = "sent"
    failed = "failed"

class EventLog(Base):
    __tablename__ = "event_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at = Column(DateTime(timezone=True), server_default=text("NOW()"), nullable=False)
    type = Column(Text, nullable=False, index=True)
    session_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    listener_id = Column(UUID(as_uuid=True), nullable=True)
    payload = Column(JSONB, nullable=False)
    # Notare: colonna TEXT (non Enum DB) ma coerente con l'EventStatus applicativo
    status = Column(Text, nullable=False, server_default=text("'received'"))
