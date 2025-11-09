# app/models/license.py
import uuid
from sqlalchemy import Column, String, Integer, Boolean, DateTime, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
from app.db.base import Base

class License(Base):
    __tablename__ = "licenses"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String(64), unique=True, nullable=False, index=True)
    duration_minutes = Column(Integer, nullable=False, default=240)  # 4h
    max_listeners = Column(Integer, nullable=False, default=10)
    is_active = Column(Boolean, nullable=False, default=False)
    activated_at = Column(DateTime(timezone=False), nullable=True)
    created_at = Column(DateTime(timezone=False), default=datetime.utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint("max_listeners IN (10,25,35,100)", name="ck_license_max_listeners_allowed"),
    )
