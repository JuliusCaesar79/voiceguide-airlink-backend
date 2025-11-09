# app/api/health.py
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime, timezone

from app.db.session import get_db
from app.models.session import Session as SessionModel
from app.models.listener import Listener
from app.models.event import Event  # ✅ import per conteggio eventi recenti

router = APIRouter(tags=["health"])

START_TIME = datetime.now(timezone.utc)


@router.get("/health")
def health(db: Session = Depends(get_db)):
    """
    Restituisce lo stato generale del sistema:
    - connessione DB
    - uptime
    - conteggio sessioni e listener attivi
    - conteggio eventi recenti (ultimi 10)
    """
    # DB status
    ok = True
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        ok = False

    now = datetime.now(timezone.utc)
    q_sessions = db.query(SessionModel)

    # Determina "active sessions" in modo adattivo
    if hasattr(SessionModel, "ended_at"):
        active_sessions = q_sessions.filter(SessionModel.ended_at == None).count()  # noqa: E711
    elif hasattr(SessionModel, "is_active"):
        active_sessions = q_sessions.filter(SessionModel.is_active == True).count()  # noqa: E712
    elif hasattr(SessionModel, "expires_at"):
        active_sessions = q_sessions.filter(SessionModel.expires_at > now).count()
    else:
        active_sessions = q_sessions.count()

    # Conteggio listener con join a sessioni "attive"
    q_listeners = db.query(Listener)
    if hasattr(Listener, "left_at"):
        q_listeners = q_listeners.filter(Listener.left_at == None)  # noqa: E711

    if hasattr(SessionModel, "ended_at"):
        connected_listeners = (
            q_listeners.join(SessionModel, Listener.session_id == SessionModel.id)
            .filter(SessionModel.ended_at == None)  # noqa: E711
            .count()
        )
    elif hasattr(SessionModel, "is_active"):
        connected_listeners = (
            q_listeners.join(SessionModel, Listener.session_id == SessionModel.id)
            .filter(SessionModel.is_active == True)  # noqa: E712
            .count()
        )
    elif hasattr(SessionModel, "expires_at"):
        connected_listeners = (
            q_listeners.join(SessionModel, Listener.session_id == SessionModel.id)
            .filter(SessionModel.expires_at > now)
            .count()
        )
    else:
        connected_listeners = q_listeners.count()

    # ✅ Conteggio eventi recenti
    recent_events_count = db.query(Event).order_by(Event.created_at.desc()).limit(10).count()

    uptime_seconds = int((datetime.now(timezone.utc) - START_TIME).total_seconds())

    return {
        "status": "ok" if ok else "degraded",
        "db_status": "ok" if ok else "error",
        "uptime_seconds": uptime_seconds,
        "active_sessions": active_sessions,
        "connected_listeners": connected_listeners,
        "recent_events": recent_events_count,
        "now": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/healthz")
def healthz():
    """
    Healthcheck leggero (non tocca il DB).
    Usato da Railway per determinare che il container è up.
    """
    return {"status": "ok"}
