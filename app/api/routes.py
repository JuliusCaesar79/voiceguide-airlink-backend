# app/api/routes.py
from __future__ import annotations

import os
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import text

# DB session
from app.db.session import get_db

# Schemi e CRUD
from app.schemas.license import LicenseActivateIn, LicenseActivateOut
from app.schemas.session import SessionOut
from app.crud import license_crud

# Modelli
from app.models.listener import Listener as ListenerModel
from app.models.session import Session as SessionModel  # ⬅️ NEW: modello Session

# Log eventi (non deve mai bloccare il flusso)
from app.core.utils import log_event

# Notifiche admin
from app.services.notify import Notifier

# Event Bus (best-effort)
try:
    from app.services.event_bus import queue_event
except Exception:
    queue_event = None

# Router modulari
from app.api import events as events_api

router = APIRouter(prefix="/api", tags=["airlink"])


# =====================================================================
# Helpers per meta info DB
# =====================================================================
def _table_exists(db: Session, table: str) -> bool:
    q = text("""
        SELECT 1
        FROM information_schema.tables
        WHERE table_name = :t
        LIMIT 1
    """)
    return db.execute(q, {"t": table}).first() is not None


def _has_col(db: Session, table: str, col: str) -> bool:
    q = text("""
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = :t AND column_name = :c
        LIMIT 1
    """)
    return db.execute(q, {"t": table, "c": col}).first() is not None


def _queue_event_if_ready(
    db: Session,
    background_tasks: BackgroundTasks,
    event_type: str,
    payload: dict,
) -> None:
    try:
        if queue_event is None:
            return
        if not _table_exists(db, "event_logs"):
            return
        queue_event(db, background_tasks, event_type, payload)
    except Exception:
        pass


# =====================================================================
# ATTIVA LICENZA
# =====================================================================
@router.post("/activate-license", response_model=LicenseActivateOut, summary="Attiva una licenza (client → guida)")
def activate_license_endpoint(
    payload: LicenseActivateIn,
    db: Session = Depends(get_db),
    background_tasks: BackgroundTasks = None,
):
    lic, rem_or_err = license_crud.activate_license(db, payload.license_code)
    if lic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="License not found")

    try:
        log_event(db, "license_activated", f"code={payload.license_code}")
    except Exception:
        pass

    _queue_event_if_ready(db, background_tasks, "license_activated", {
        "license_code": payload.license_code,
        "license_id": str(lic.id),
        "remaining_minutes": rem_or_err,
        "activated_at": lic.activated_at.isoformat() if getattr(lic, "activated_at", None) else None,
    })

    return {
        "id": str(lic.id),
        "code": lic.code,
        "is_active": lic.is_active,
        "activated_at": lic.activated_at,
        "remaining_minutes": rem_or_err,
    }


# =====================================================================
# START SESSION
# =====================================================================
@router.post("/start-session", response_model=SessionOut, summary="Avvia una sessione voce (guida)")
def start_session_endpoint(
    license_code: str,
    max_listeners: int | None = None,
    db: Session = Depends(get_db),
    background_tasks: BackgroundTasks = None,
):
    lic = license_crud.get_license_by_code(db, license_code)
    if not lic:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="License not found")

    session, err = license_crud.start_session_for_license(db, lic, requested_max_listeners=max_listeners)
    if err:
        mapping = {
            "license_not_active": (status.HTTP_409_CONFLICT, "License not active"),
            "license_expired": (status.HTTP_409_CONFLICT, "License expired"),
            "invalid_max_listeners": (status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid max_listeners"),
            "pin_generation_failed": (status.HTTP_500_INTERNAL_SERVER_ERROR, "pin_generation_failed"),
        }
        sc, msg = mapping.get(err, (status.HTTP_500_INTERNAL_SERVER_ERROR, err))
        raise HTTPException(status_code=sc, detail=msg)

    try:
        log_event(db, "session_started", f"pin={session.pin}", session_id=str(session.id))
    except Exception:
        pass

    _queue_event_if_ready(db, background_tasks, "session_started", {
        "session_id": str(session.id),
        "license_code": license_code,
        "pin": session.pin,
        "max_listeners": max_listeners,
        "started_at": session.started_at.isoformat() if getattr(session, "started_at", None) else None,
    })

    try:
        n = Notifier()
        n.notify("Session Started", {
            "event": "session_started",
            "session_id": str(session.id),
            "license_code": license_code,
            "pin": session.pin,
        })
    except Exception:
        pass

    return session


# =====================================================================
# JOIN PIN (ospite)
# =====================================================================
@router.post("/join-pin", summary="Entra in una sessione tramite PIN (ascoltatore)")
def join_pin_endpoint(
    pin: str,
    display_name: str | None = None,
    db: Session = Depends(get_db),
    background_tasks: BackgroundTasks = None,
):
    listener, err = license_crud.join_session_by_pin(db, pin, display_name)
    if err:
        mapping = {
            "session_not_found": (status.HTTP_404_NOT_FOUND, "Session not found"),
            "session_expired": (status.HTTP_410_GONE, "Session expired"),
            "session_full": (status.HTTP_409_CONFLICT, "Session full"),
        }
        sc, msg = mapping.get(err, (status.HTTP_400_BAD_REQUEST, err))
        raise HTTPException(status_code=sc, detail=msg)

    try:
        log_event(db, "listener_joined", f"listener={listener.id}", session_id=str(listener.session_id))
    except Exception:
        pass

    _queue_event_if_ready(db, background_tasks, "listener_joined", {
        "session_id": str(listener.session_id),
        "listener_id": str(listener.id),
        "pin": pin,
        "display_name": display_name,
    })

    return {
        "id": str(listener.id),
        "session_id": str(listener.session_id),
        "joined_at": listener.joined_at,
    }


# =====================================================================
# GET LISTENER STATUS (nuovo)
# =====================================================================
@router.get("/listeners/{listener_id}", summary="Stato listener (polling ospite)")
def get_listener_status(
    listener_id: str,
    db: Session = Depends(get_db),
):
    listener = (
        db.query(ListenerModel)
        .filter(ListenerModel.id == listener_id)
        .first()
    )

    if listener is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Listener not found",
        )

    return {
        "id": str(listener.id),
        "session_id": str(listener.session_id),
        "is_connected": listener.is_connected,
        "joined_at": listener.joined_at,
        "left_at": listener.left_at,
    }


# =====================================================================
# LEAVE LISTENER
# =====================================================================
@router.post("/listeners/{listener_id}/leave", summary="Lascia il tour (ascoltatore)")
def leave_listener_endpoint(
    listener_id: str,
    db: Session = Depends(get_db),
    background_tasks: BackgroundTasks = None,
):
    listener = (
        db.query(ListenerModel)
        .filter(ListenerModel.id == listener_id)
        .first()
    )

    if listener is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Listener not found",
        )

    if not listener.is_connected:
        return {
            "ok": True,
            "listener_id": str(listener.id),
            "session_id": str(listener.session_id),
            "status": "already_disconnected",
        }

    listener.disconnect()

    try:
        log_event(
            db,
            "listener_left",
            f"listener={listener.id};reason=manual_leave",
            session_id=str(listener.session_id),
        )
    except Exception:
        pass

    _queue_event_if_ready(db, background_tasks, "listener_left", {
        "session_id": str(listener.session_id),
        "listener_id": str(listener.id),
        "reason": "manual_leave",
    })

    db.commit()
    db.refresh(listener)

    return {
        "ok": True,
        "listener_id": str(listener.id),
        "session_id": str(listener.session_id),
        "status": "disconnected",
    }


# =====================================================================
# END SESSION
# =====================================================================
@router.post("/end-session", summary="Termina una sessione (guida/admin)")
def end_session_endpoint(
    session_id: str,
    db: Session = Depends(get_db),
    background_tasks: BackgroundTasks = None,
):
    ok = license_crud.end_session(db, session_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    try:
        log_event(db, "session_ended", session_id=session_id)
    except Exception:
        pass

    _queue_event_if_ready(db, background_tasks, "session_ended", {
        "session_id": session_id,
    })

    return {"ok": True}


# =====================================================================
# SESSION STATUS (polling guida)
# =====================================================================
@router.get(
    "/sessions/{session_id}/status",
    summary="Stato sessione (guida - polling)",
)
def get_session_status_endpoint(
    session_id: str,
    db: Session = Depends(get_db),
):
    session = (
        db.query(SessionModel)
        .filter(SessionModel.id == session_id)
        .first()
    )

    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )

    # Calcolo secondi residui rispetto a expires_at
    now = datetime.utcnow()
    remaining_seconds = int((session.expires_at - now).total_seconds())
    if remaining_seconds < 0:
        remaining_seconds = 0

    return {
        "id": str(session.id),
        "pin": session.pin,
        "is_active": session.is_active and remaining_seconds > 0,
        "max_listeners": session.max_listeners,
        "current_listeners": session.active_listeners,
        "started_at": session.started_at,
        "ended_at": session.ended_at,
        "expires_at": session.expires_at,
        "remaining_seconds": remaining_seconds,
    }


# =====================================================================
# Admin quick stats
# =====================================================================
@router.get(
    "/admin/quick-stats",
    summary="Quick stats backend (admin)",
    tags=["admin"],
)
def admin_quick_stats(
    db: Session = Depends(get_db),
):
    now = datetime.utcnow()
    since = now - timedelta(hours=24)
    version = os.getenv("APP_VERSION", "dev")

    db_ok = True
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        db_ok = False

    sessions_24h = None
    listeners_24h = None
    events_24h = None
    recent_sessions = []

    if _table_exists(db, "sessions"):
        has_started_at = _has_col(db, "sessions", "started_at")

        if has_started_at:
            sessions_24h = db.execute(text("""
                SELECT COUNT(*)::bigint
                FROM sessions
                WHERE started_at >= :since
            """), {"since": since}).scalar()

    return {
        "status": "ok" if db_ok else "degraded",
        "version": version,
        "now_utc": now.isoformat() + "Z",
        "window_hours": 24,
        "db_ok": db_ok,
        "counters": {
            "sessions_last_24h": sessions_24h,
            "listeners_last_24h": listeners_24h,
            "events_last_24h": events_24h,
        },
        "recent_sessions": recent_sessions,
    }


# =====================================================================
# Mount router relativi
# =====================================================================
router.include_router(events_api.router)
