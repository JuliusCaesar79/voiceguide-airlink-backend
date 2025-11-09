# app/core/utils.py
import secrets
import string
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session
from app.models.event import Event

# ------------------------------------------------------------
# PIN Generation and Time Helpers
# ------------------------------------------------------------

PIN_ALPHABET = string.ascii_uppercase + string.digits

def gen_pin(length: int = 6) -> str:
    """Genera un PIN alfanumerico casuale (default 6 caratteri)."""
    return "".join(secrets.choice(PIN_ALPHABET) for _ in range(length))

def utcnow():
    """Restituisce l'orario UTC corrente."""
    return datetime.utcnow()

def compute_expiry(start: datetime, minutes: int):
    """Calcola la data di scadenza partendo da un istante e minuti di durata."""
    return start + timedelta(minutes=minutes)

# ------------------------------------------------------------
# Event Logging Utility (NEW)
# ------------------------------------------------------------

def log_event(
    db: Session,
    event_type: str,
    description: Optional[str] = None,
    session_id: Optional[str] = None,
):
    """
    Registra un evento applicativo nella tabella 'events'.

    :param db: sessione SQLAlchemy attiva
    :param event_type: tipo evento (es. 'license_activated', 'session_started', 'listener_joined', 'session_ended')
    :param description: testo descrittivo opzionale
    :param session_id: eventuale riferimento a sessione
    """
    try:
        ev = Event(type=event_type, description=description, session_id=session_id)
        db.add(ev)
        db.commit()
    except Exception as e:
        # In caso di errore, non bloccare mai il flusso principale
        db.rollback()
        print(f"[log_event] errore durante il salvataggio evento: {e}")
