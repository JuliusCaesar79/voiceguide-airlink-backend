# app/models/session.py
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, Boolean, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base import Base


class Session(Base):
    __tablename__ = "sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Licenza che ha avviato la sessione (guida)
    license_id = Column(UUID(as_uuid=True), ForeignKey("licenses.id", ondelete="CASCADE"), nullable=False)

    # PIN alfanumerico di 6 caratteri per il join degli ospiti
    pin = Column(String(6), unique=True, nullable=False, index=True)

    # Timestamp di avvio (UTC). Manteniamo timezone=False per coerenza con il resto del progetto.
    started_at = Column(DateTime(timezone=False), default=datetime.utcnow, nullable=False)

    # Timestamp di chiusura (nullable) — usato per KPI e per capire se la sessione è ancora attiva
    ended_at = Column(DateTime(timezone=False), nullable=True)

    # Scadenza hard (es. 90 minuti, 2 ore, ecc.) — settata alla creazione della sessione
    expires_at = Column(DateTime(timezone=False), nullable=False)

    # Limite massimo di ascoltatori (in base al pacchetto/credito)
    max_listeners = Column(Integer, nullable=False)

    # Flag rapido: sessione attiva/sospesa (non sostituisce ended_at)
    is_active = Column(Boolean, nullable=False, default=True)

    # Backref verso License
    license = relationship("License", backref="sessions")

    # Indici utili per stats e filtri amministrativi
    __table_args__ = (
        Index("ix_sessions_started_at", "started_at"),
        Index("ix_sessions_ended_at", "ended_at"),
        Index("ix_sessions_is_active", "is_active"),
    )
