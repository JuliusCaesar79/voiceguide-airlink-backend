# app/models/session.py
import uuid
from sqlalchemy import Column, String, Integer, Boolean, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime, timedelta
from sqlalchemy.orm import relationship
from app.db.base import Base

class Session(Base):
    __tablename__ = "sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    license_id = Column(UUID(as_uuid=True), ForeignKey("licenses.id", ondelete="CASCADE"), nullable=False)
    pin = Column(String(6), unique=True, nullable=False, index=True)
    started_at = Column(DateTime(timezone=False), default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime(timezone=False), nullable=False)
    max_listeners = Column(Integer, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)

    license = relationship("License", backref="sessions")
