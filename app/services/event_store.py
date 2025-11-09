from typing import Optional, Iterable
from datetime import datetime
from sqlalchemy.orm import Session

from app.models.event_log import EventLog

def store_received_event(db: Session, payload: dict) -> EventLog:
    """
    Salva un evento ricevuto (webhook) su DB.
    """
    ev = EventLog(
        type=payload.get("type", "unknown"),
        session_id=payload.get("session_id"),
        listener_id=payload.get("listener_id"),
        payload=payload,
        status="received",
    )
    db.add(ev)
    db.commit()
    db.refresh(ev)
    return ev

def query_events(
    db: Session,
    *,
    type: Optional[str] = None,
    session_id: Optional[str] = None,
    since: Optional[datetime] = None,
    to: Optional[datetime] = None,
) -> Iterable[EventLog]:
    """
    Query base per export/analytics con filtri comuni.
    """
    q = db.query(EventLog)
    if type:
        q = q.filter(EventLog.type == type)
    if session_id:
        q = q.filter(EventLog.session_id == session_id)
    if since:
        q = q.filter(EventLog.created_at >= since)
    if to:
        q = q.filter(EventLog.created_at < to)
    return q.order_by(EventLog.created_at.desc())
