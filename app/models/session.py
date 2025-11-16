# app/models/session.py
import uuid
from datetime import datetime
from sqlalchemy import (
    Column,
    String,
    Integer,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base import Base


class Session(Base):
    __tablename__ = "sessions"

    # UUID della sessione
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Licenza che ha avviato la sessione (guida)
    license_id = Column(
        UUID(as_uuid=True),
        ForeignKey("licenses.id", ondelete="CASCADE"),
        nullable=False,
    )

    # PIN di 6 caratteri per il join degli ospiti
    pin = Column(String(6), unique=True, nullable=False, index=True)

    # Timestamp di avvio (UTC, timezone=False per coerenza)
    started_at = Column(
        DateTime(timezone=False),
        default=datetime.utcnow,
        nullable=False,
    )

    # Timestamp di chiusura (nullable)
    ended_at = Column(
        DateTime(timezone=False),
        nullable=True,
    )

    # Scadenza hard (es. 4h) settata alla creazione
    expires_at = Column(
        DateTime(timezone=False),
        nullable=False,
    )

    # Numero massimo di ascoltatori (in base al pacchetto/credito)
    max_listeners = Column(Integer, nullable=False)

    # Flag rapido di stato (sessione attiva finché non viene chiusa)
    is_active = Column(
        Boolean,
        nullable=False,
        default=True,
        index=True,
    )

    # --- RELAZIONI -----------------------------------------------------
    # Backref verso License
    license = relationship("License", backref="sessions")

    # Listener collegati a questa sessione (ONE → MANY)
    listeners = relationship(
        "Listener",
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    # --- INDICI --------------------------------------------------------
    __table_args__ = (
        Index("ix_sessions_started_at", "started_at"),
        Index("ix_sessions_ended_at", "ended_at"),
        Index("ix_sessions_is_active", "is_active"),
    )

    # --- PROPERTY UTILI ------------------------------------------------
    @property
    def is_expired(self) -> bool:
        """
        Ritorna True se la sessione è scaduta rispetto a expires_at.
        """
        return datetime.utcnow() >= self.expires_at

    @property
    def is_closable(self) -> bool:
        """
        Ritorna True se la sessione è attiva e scaduta.
        (Usato nel job auto-close)
        """
        return self.is_active and self.is_expired

    @property
    def active_listeners(self) -> int:
        """
        Ritorna il numero di listener ancora connessi.
        (In futuro compatibile con Agora)
        """
        return sum(1 for l in self.listeners if l.is_connected)
