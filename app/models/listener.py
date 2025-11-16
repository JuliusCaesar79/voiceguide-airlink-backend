# app/models/listener.py
import uuid
from datetime import datetime
from sqlalchemy import (
    Column,
    String,
    DateTime,
    ForeignKey,
    Boolean,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base import Base


class Listener(Base):
    __tablename__ = "listeners"

    # UUID univoco del listener
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Sessione a cui il listener appartiene
    session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Nome visualizzato dell'ospite (opzionale)
    display_name = Column(String(128), nullable=True)

    # Timestamp ingresso (UTC)
    joined_at = Column(
        DateTime(timezone=False),
        default=datetime.utcnow,
        nullable=False,
    )

    # Timestamp uscita (null finché l'ascoltatore resta collegato)
    left_at = Column(
        DateTime(timezone=False),
        nullable=True,
    )

    # Flag booleano: True = collegato, False = disconnesso
    # (Serve per chiusura automatica, pulsante "Lascia il tour", e Agora)
    is_connected = Column(
        Boolean,
        nullable=False,
        default=True,
    )

    # Relazione inversa verso Session
    session = relationship(
        "Session",
        back_populates="listeners",
    )

    # ----------------------------------------------------------------------
    # PROPERTY UTILI
    # ----------------------------------------------------------------------
    @property
    def is_active(self) -> bool:
        """
        Alias per compatibilità: un listener è attivo se è ancora collegato.
        """
        return self.is_connected

    def disconnect(self):
        """
        Metodo comodo per disconnettere il listener.
        Imposta left_at e is_connected=False.
        """
        if self.is_connected:
            self.is_connected = False
            self.left_at = datetime.utcnow()
