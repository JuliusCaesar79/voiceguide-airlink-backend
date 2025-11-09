# app/models/listener.py
import uuid
from sqlalchemy import Column, String, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
from sqlalchemy.orm import relationship
from app.db.base import Base

class Listener(Base):
    __tablename__ = "listeners"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    display_name = Column(String(128), nullable=True)
    joined_at = Column(DateTime(timezone=False), default=datetime.utcnow, nullable=False)

    session = relationship("Session", backref="listeners")
