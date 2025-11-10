# app/api/stats.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/overview")
def stats_overview(db: Session = Depends(get_db)):
    """
    KPI minimi per il monitoraggio:
      - sessions_last_24h: numero di sessioni iniziate nelle ultime 24 ore
      - avg_session_minutes: durata media (minuti) delle sessioni chiuse nelle ultime 24 ore
      - active_now: sessioni attive in questo momento

    Assunzioni schema:
      - Tabella: sessions
      - Colonne: started_at (TIMESTAMP/TZ), ended_at (TIMESTAMP/TZ nullable)
    """
    now_utc = datetime.now(timezone.utc)
    since_utc = now_utc - timedelta(hours=24)

    # 1) Sessioni iniziate nelle ultime 24 ore
    q_last24 = text("""
        SELECT COUNT(*)::BIGINT AS c
        FROM sessions
        WHERE started_at >= :since
    """)
    sessions_last_24h = db.execute(q_last24, {"since": since_utc}).scalar() or 0

    # 2) Durata media (in minuti) delle sessioni CHIUSE nelle ultime 24 ore
    q_avg = text("""
        SELECT AVG(EXTRACT(EPOCH FROM (ended_at - started_at)) / 60.0) AS avg_min
        FROM sessions
        WHERE ended_at IS NOT NULL
          AND started_at >= :since
          AND ended_at <= :now
    """)
    avg_session_minutes = db.execute(q_avg, {"since": since_utc, "now": now_utc}).scalar()
    avg_session_minutes = round(float(avg_session_minutes), 2) if avg_session_minutes is not None else 0.0

    # 3) Sessioni attive ora
    q_active = text("""
        SELECT COUNT(*)::BIGINT AS c
        FROM sessions
        WHERE started_at <= :now
          AND (ended_at IS NULL OR ended_at > :now)
    """)
    active_now = db.execute(q_active, {"now": now_utc}).scalar() or 0

    return {
        "range": {
            "from": since_utc.isoformat(),
            "to": now_utc.isoformat(),
            "bucket": "24h"
        },
        "kpi": {
            "sessions_last_24h": int(sessions_last_24h),
            "avg_session_minutes": avg_session_minutes,
            "active_now": int(active_now),
        }
    }
