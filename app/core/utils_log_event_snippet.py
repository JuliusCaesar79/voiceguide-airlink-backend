from sqlalchemy.orm import Session
from typing import Optional
from app.models.event import Event

def log_event(db: Session, event_type: str, description: Optional[str] = None, session_id: Optional[str] = None):
    ev = Event(type=event_type, description=description, session_id=session_id)
    db.add(ev)
    db.commit()
