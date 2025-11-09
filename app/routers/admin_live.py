from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import select, func, text

from app.db.session import get_db
from app.models.event_log import EventLog

router = APIRouter(prefix="/api/admin/live", tags=["admin:live"])


# ------------------------------ helpers ------------------------------
def _utcnow() -> datetime:
    return datetime.now(timezone.utc)

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
# ---------------------------------------------------------------------


@router.get("", summary="Dashboard live: KPI & eventi recenti")
def live(
    db: Session = Depends(get_db),
    bucket: str = Query(default="5m", description="Intervallo KPI: 5m, 1h, 24h"),
):
    """
    KPI rapidi basati su EventLog + metriche extra:
    - peak_listeners: massimo ascoltatori per sessione (globale)
    - avg_session_minutes: durata media delle sessioni concluse (minuti)
    Il tutto con fallback se mancano tabelle/colonne.
    """
    now = _utcnow()
    ranges = {
        "5m": now - timedelta(minutes=5),
        "1h": now - timedelta(hours=1),
        "24h": now - timedelta(hours=24),
    }
    window = ranges.get(bucket, ranges["5m"])

    # ---------------- KPI base da EventLog ----------------
    q_total = db.execute(
        select(func.count()).select_from(EventLog).where(EventLog.created_at >= window)
    ).scalar() or 0

    def count_type(t: str) -> int:
        return (
            db.execute(
                select(func.count())
                .select_from(EventLog)
                .where(EventLog.created_at >= window, EventLog.event_type == t)
            ).scalar()
            or 0
        )

    started = count_type("session_started")
    ended = count_type("session_ended")
    joined = count_type("listener_joined")

    # Ultimi N eventi (EventLog) per lista "recent"
    last = (
        db.execute(
            select(EventLog).order_by(EventLog.created_at.desc()).limit(50)
        )
        .scalars()
        .all()
    )

    recent: List[Dict[str, Any]] = [
        {
            "id": str(e.id),
            "t": e.created_at.astimezone(timezone.utc).isoformat() if e.created_at else None,
            "type": e.event_type,
            "status": e.status,     # stato delivery webhook
            "retries": e.retries,
            "payload": e.payload if hasattr(e, "payload") else None,
        }
        for e in last
    ]

    # ---------------- Metriche extra ----------------
    peak_listeners = None
    avg_session_minutes = None

    has_sessions = _table_exists(db, "sessions")
    has_joins = _table_exists(db, "joins")

    # Peak listeners
    if has_sessions:
        has_listeners_col = _has_col(db, "sessions", "listeners_count")
        if has_listeners_col:
            peak_listeners = db.execute(text("""
                SELECT COALESCE(MAX(listeners_count), 0)::int FROM sessions
            """)).scalar()
        elif has_joins:
            peak_listeners = db.execute(text("""
                SELECT COALESCE(MAX(cnt), 0)::int
                FROM (
                    SELECT session_id, COUNT(*) AS cnt
                    FROM joins
                    GROUP BY session_id
                ) t
            """)).scalar()
        else:
            peak_listeners = 0

        # Avg session minutes (solo per sessioni concluse)
        has_started_at = _has_col(db, "sessions", "started_at")
        has_ended_at = _has_col(db, "sessions", "ended_at")
        if has_started_at and has_ended_at:
            avg_seconds = db.execute(text("""
                SELECT AVG(EXTRACT(EPOCH FROM (ended_at - started_at)))
                FROM sessions
                WHERE started_at IS NOT NULL AND ended_at IS NOT NULL
                      AND ended_at > started_at
            """)).scalar()
            if avg_seconds is not None:
                avg_session_minutes = round(float(avg_seconds) / 60.0, 2)

    # Distribuzione stati delivery (EventLog) nella finestra
    status_counts = db.execute(text("""
        SELECT status, COUNT(*)::int
        FROM event_logs
        WHERE created_at >= :win
        GROUP BY status
    """), {"win": window}).all()
    deliveries = {s: c for (s, c) in status_counts}

    return {
        "range": {"from": window.isoformat(), "to": now.isoformat(), "bucket": bucket},
        "kpi": {
            "events_last_5m": q_total if bucket == "5m" else None,  # mantenuto per retro-compat
            "session_started": started,
            "session_ended": ended,
            "listener_joined": joined,
            "peak_listeners": int(peak_listeners) if peak_listeners is not None else None,
            "avg_session_minutes": float(avg_session_minutes) if avg_session_minutes is not None else None,
            "deliveries": deliveries,
        },
        "recent": recent,
    }
