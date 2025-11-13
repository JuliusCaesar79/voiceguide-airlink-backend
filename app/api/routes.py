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

# Log eventi (non deve mai bloccare il flusso)
from app.core.utils import log_event

# Notifiche admin (console/email/webhook)
from app.services.notify import Notifier

# Event Bus (nuovo) – safe import
try:
    from app.services.event_bus import queue_event
except Exception:
    queue_event = None  # fallback: disabilitato finché non presente

# Router modulari "relativi" (compatibili con prefix="/api")
from app.api import events as events_api
# ⚠️ RIMOSSO: from app.api import health as health_api  (health gestito in app/routers/health.py)

router = APIRouter(prefix="/api", tags=["airlink"])


# ------------------------------ helpers locali ------------------------------
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
    """Enqueue evento nel nostro Event Store/Webhook solo se pronto. Best-effort, no raise."""
    try:
        if queue_event is None:
            return
        if not _table_exists(db, "event_logs"):
            return
        queue_event(db, background_tasks, event_type, payload)
    except Exception:
        # Non deve mai bloccare la richiesta principale
        pass
# ---------------------------------------------------------------------------


@router.post("/activate-license", response_model=LicenseActivateOut, summary="Attiva una licenza (client → guida)")
def activate_license_endpoint(
    payload: LicenseActivateIn,
    db: Session = Depends(get_db),
    background_tasks: BackgroundTasks = None,  # FastAPI lo gestisce come special param, non body
):
    lic, rem_or_err = license_crud.activate_license(db, payload.license_code)
    if lic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="License not found")

    try:
        log_event(db, "license_activated", f"code={payload.license_code}")
    except Exception:
        pass

    # Event Bus (best-effort)
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

    # log: session_started (best-effort)
    try:
        log_event(db, "session_started", f"pin={session.pin}", session_id=str(session.id))
    except Exception:
        pass

    # Event Bus (best-effort)
    _queue_event_if_ready(db, background_tasks, "session_started", {
        "session_id": str(session.id),
        "license_code": license_code,
        "pin": session.pin,
        "max_listeners": max_listeners,
        "started_at": session.started_at.isoformat() if getattr(session, "started_at", None) else None,
    })

    # Notifica Admin (best-effort)
    try:
        n = Notifier()
        n.notify("Session Started", {
            "event": "session_started",
            "session_id": str(session.id),
            "license_code": license_code,
            "pin": session.pin,
            "max_listeners": max_listeners,
            "started_at": session.started_at.isoformat() if hasattr(session, "started_at") and session.started_at else None,
        })
    except Exception:
        pass

    return session


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

    # log: listener_joined (best-effort)
    try:
        log_event(db, "listener_joined", f"listener={listener.id}", session_id=str(listener.session_id))
    except Exception:
        pass

    # Event Bus (best-effort)
    _queue_event_if_ready(db, background_tasks, "listener_joined", {
        "session_id": str(listener.session_id),
        "listener_id": str(listener.id),
        "pin": pin,
        "display_name": display_name,
        "joined_at": listener.joined_at.isoformat() if getattr(listener, "joined_at", None) else None,
    })

    # Notifica Admin (best-effort)
    try:
        # Pin dalla tabella sessions se disponibile
        sess_pin = None
        if _table_exists(db, "sessions") and _has_col(db, "sessions", "pin"):
            sess_pin = db.execute(
                text("SELECT pin FROM sessions WHERE id = :sid LIMIT 1"),
                {"sid": str(listener.session_id)},
            ).scalar()

        # Metadati opzionali dalla tabella joins (se esistono le colonne)
        meta = {}
        if _table_exists(db, "joins"):
            cols = {
                "client_version": _has_col(db, "joins", "client_version"),
                "device": _has_col(db, "joins", "device"),
                "network_quality": _has_col(db, "joins", "network_quality"),
                "city": _has_col(db, "joins", "city"),
                "country": _has_col(db, "country") if _has_col(db, "joins", "country") else False,
            }
            if any(cols.values()):
                row = db.execute(text(f"""
                    SELECT
                      {"client_version" if cols["client_version"] else "NULL::text"} AS client_version,
                      {"device" if cols["device"] else "NULL::text"} AS device,
                      {"network_quality" if cols["network_quality"] else "NULL::text"} AS network_quality,
                      {"city" if cols["city"] else "NULL::text"} AS city,
                      {"country" if cols["country"] else "NULL::text"} AS country
                    FROM joins
                    WHERE id = :jid
                    LIMIT 1
                """), {"jid": str(listener.id)}).mappings().first()
                if row:
                    meta = {k: row[k] for k in row.keys() if row[k] is not None}

        n = Notifier()
        n.notify("Listener Joined", {
            "event": "listener_joined",
            "session_id": str(listener.session_id),
            "listener_id": str(listener.id),
            "pin": sess_pin or pin,
            "display_name": display_name,
            "joined_at": listener.joined_at.isoformat() if hasattr(listener, "joined_at") and listener.joined_at else None,
            **meta,
        })
    except Exception:
        pass

    return {
        "id": str(listener.id),
        "session_id": str(listener.session_id),
        "joined_at": listener.joined_at,
    }


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

    # Event Bus (best-effort)
    _queue_event_if_ready(db, background_tasks, "session_ended", {
        "session_id": session_id,
    })

    # Notifica Admin (best-effort)
    try:
        has_sessions = _table_exists(db, "sessions")
        has_events   = _table_exists(db, "events")
        has_joins    = _table_exists(db, "joins")

        has_started_at  = has_sessions and _has_col(db, "sessions", "started_at")
        has_ended_at    = has_sessions and _has_col(db, "sessions", "ended_at")
        has_pin         = has_sessions and _has_col(db, "sessions", "pin")
        has_listeners   = has_sessions and _has_col(db, "sessions", "listeners_count")
        has_license_col = has_sessions and _has_col(db, "sessions", "license_code")

        row = None
        if has_sessions:
            row = db.execute(text(f"""
                SELECT
                  s.id,
                  {"s.pin" if has_pin else "NULL::text"} AS pin,
                  {"s.started_at" if has_started_at else "NULL::timestamp"} AS started_at,
                  {"s.ended_at" if has_ended_at else "NULL::timestamp"} AS ended_at,
                  {"s.listeners_count" if has_listeners else "NULL::int"} AS listeners_count,
                  {"s.license_code" if has_license_col else "NULL::text"} AS license_code
                FROM sessions s
                WHERE s.id = :sid
                LIMIT 1
            """), {"sid": session_id}).mappings().first()

        pin = row["pin"] if row else None
        started_at = row["started_at"] if row else None
        ended_at = row["ended_at"] if row else None
        listeners_count = row["listeners_count"] if row else None
        license_code = row["license_code"] if row else None

        if (ended_at is None) and has_events:
            ended_at = db.execute(text("""
                SELECT MAX(e.created_at) FROM events e
                WHERE e.type = 'session_ended' AND e.session_id = :sid
            """), {"sid": session_id}).scalar()

        if listeners_count is None:
            if has_joins:
                listeners_count = db.execute(text("""
                    SELECT COUNT(*)::int FROM joins WHERE session_id = :sid
                """), {"sid": session_id}).scalar()
            if (listeners_count is None) and has_events and _has_col(db, "events", "payload"):
                listeners_count = db.execute(text("""
                    SELECT MAX((e.payload->>'listeners_count')::int)
                    FROM events e
                    WHERE e.type='session_ended' AND e.session_id = :sid
                """), {"sid": session_id}).scalar()

        duration_seconds = None
        if started_at and ended_at:
            duration_seconds = db.execute(text("""
                SELECT COALESCE(EXTRACT(EPOCH FROM (:ended - :started)),0)::bigint
            """), {"ended": ended_at, "started": started_at}).scalar()

        n = Notifier()
        n.notify("Session Ended", {
            "event": "session_ended",
            "session_id": session_id,
            "pin": pin,
            "license_code": license_code,
            "ended_at": ended_at.isoformat() if hasattr(ended_at, "isoformat") else (str(ended_at) if ended_at else None),
            "started_at": started_at.isoformat() if hasattr(started_at, "isoformat") else (str(started_at) if started_at else None),
            "duration_seconds": int(duration_seconds) if duration_seconds is not None else None,
            "listeners_count": int(listeners_count) if listeners_count is not None else None,
        })
    except Exception:
        pass

    return {"ok": True}


# --------------------------- Admin quick stats ------------------------------
@router.get(
    "/admin/quick-stats",
    summary="Quick stats backend (admin)",
    tags=["admin"],
)
def admin_quick_stats(
    db: Session = Depends(get_db),
):
    """
    Mini-dashboard JSON:
    - stato DB
    - versione app
    - conteggi ultime 24h
    - ultime sessioni (fino a 5) se la tabella esiste
    """
    now = datetime.utcnow()
    since = now - timedelta(hours=24)
    version = os.getenv("APP_VERSION", "dev")

    # Stato DB base
    db_ok = True
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        db_ok = False

    sessions_24h = None
    listeners_24h = None
    events_24h = None
    recent_sessions: list[dict] = []

    # Conteggio sessioni ultime 24h
    if _table_exists(db, "sessions"):
        has_started_at = _has_col(db, "sessions", "started_at")
        if has_started_at:
            sessions_24h = db.execute(text("""
                SELECT COUNT(*)::bigint
                FROM sessions
                WHERE started_at >= :since
            """), {"since": since}).scalar()

        # Ultime 5 sessioni
        has_ended_at = _has_col(db, "sessions", "ended_at")
        has_pin = _has_col(db, "sessions", "pin")
        has_listeners = _has_col(db, "sessions", "listeners_count")
        has_license_col = _has_col(db, "sessions", "license_code")

        rows = db.execute(text(f"""
            SELECT
              s.id,
              {"s.pin" if has_pin else "NULL::text"} AS pin,
              {"s.started_at" if has_started_at else "NULL::timestamp"} AS started_at,
              {"s.ended_at" if has_ended_at else "NULL::timestamp"} AS ended_at,
              {"s.listeners_count" if has_listeners else "NULL::int"} AS listeners_count,
              {"s.license_code" if has_license_col else "NULL::text"} AS license_code
            FROM sessions s
            ORDER BY
              {"s.started_at DESC NULLS LAST," if has_started_at else ""}
              s.id DESC
            LIMIT 5
        """)).mappings().all()

        for r in rows:
            recent_sessions.append({
                "id": str(r["id"]),
                "pin": r["pin"],
                "license_code": r.get("license_code"),
                "started_at": r["started_at"].isoformat() if hasattr(r["started_at"], "isoformat") else (str(r["started_at"]) if r["started_at"] else None),
                "ended_at": r["ended_at"].isoformat() if hasattr(r["ended_at"], "isoformat") else (str(r["ended_at"]) if r["ended_at"] else None),
                "listeners_count": int(r["listeners_count"]) if r["listeners_count"] is not None else None,
            })

    # Conteggio listeners ultime 24h (joins)
    if _table_exists(db, "joins") and _has_col(db, "joins", "joined_at"):
        listeners_24h = db.execute(text("""
            SELECT COUNT(*)::bigint
            FROM joins
            WHERE joined_at >= :since
        """), {"since": since}).scalar()

    # Conteggio eventi ultime 24h
    if _table_exists(db, "events") and _has_col(db, "events", "created_at"):
        events_24h = db.execute(text("""
            SELECT COUNT(*)::bigint
            FROM events
            WHERE created_at >= :since
        """), {"since": since}).scalar()

    return {
        "status": "ok" if db_ok else "degraded",
        "version": version,
        "now_utc": now.isoformat() + "Z",
        "window_hours": 24,
        "db_ok": db_ok,
        "counters": {
            "sessions_last_24h": int(sessions_24h) if sessions_24h is not None else None,
            "listeners_last_24h": int(listeners_24h) if listeners_24h is not None else None,
            "events_last_24h": int(events_24h) if events_24h is not None else None,
        },
        "recent_sessions": recent_sessions,
    }
# ---------------------------------------------------------------------------


# 🔗 monta qui SOLO i router con path RELATIVI (compatibili con /api)
router.include_router(events_api.router)

# ⚠️ RIMOSSI include duplicati:
# - health_api.router (health è in app/routers/health.py e montato in main.py)
# - admin_live_router e admin_events_router (già montati in main.py)
