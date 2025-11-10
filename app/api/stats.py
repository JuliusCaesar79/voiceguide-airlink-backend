# app/api/stats.py
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/overview")
def stats_overview(db: Session = Depends(get_db)):
    """
    KPI minimi (safe-mode):
      - sessions_last_24h
      - avg_session_minutes
      - active_now
    Se tabella/colonne non esistono, restituisce KPI=0 e una 'note' esplicativa.
    Assunzione tabella: public.sessions(started_at, ended_at)
    """
    now_utc = datetime.now(timezone.utc)
    since_utc = now_utc - timedelta(hours=24)
    version = os.getenv("APP_VERSION", "dev")

    def ok_payload(sessions_last_24h: int, avg_session_minutes: float, active_now: int, note: str | None = None):
        out = {
            "range": {"from": since_utc.isoformat(), "to": now_utc.isoformat(), "bucket": "24h"},
            "kpi": {
                "sessions_last_24h": int(sessions_last_24h),
                "avg_session_minutes": round(float(avg_session_minutes), 2),
                "active_now": int(active_now),
            },
            "version": version,
        }
        if note:
            out["note"] = note
        return out

    # 0) Esistenza tabella sessions
    try:
        exists = db.execute(
            text("SELECT to_regclass('public.sessions') IS NOT NULL AS exists")
        ).scalar()
        if not exists:
            return ok_payload(0, 0.0, 0, note="Tabella public.sessions assente; KPI settati a 0.")
    except Exception as e:
        return ok_payload(0, 0.0, 0, note=f"Errore verifica tabella sessions: {e}")

    # 1) Esistenza colonne necessarie
    try:
        q_cols = text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'sessions'
        """)
        cols = {row[0] for row in db.execute(q_cols).fetchall()}
        missing = {c for c in ("started_at", "ended_at") if c not in cols}
        if missing:
            return ok_payload(0, 0.0, 0, note=f"Colonne mancanti in sessions: {', '.join(sorted(missing))}.")
    except Exception as e:
        return ok_payload(0, 0.0, 0, note=f"Errore lettura colonne sessions: {e}")

    # 2) Query KPI (robuste)
    try:
        # 2.1 Sessioni iniziate nelle ultime 24h
        q_last24 = text("""
            SELECT COUNT(*)::BIGINT AS c
            FROM public.sessions
            WHERE started_at >= :since
        """)
        sessions_last_24h = db.execute(q_last24, {"since": since_utc}).scalar() or 0

        # 2.2 Durata media (minuti) delle sessioni CHIUSE nelle ultime 24h
        q_avg = text("""
            SELECT AVG(EXTRACT(EPOCH FROM (ended_at - started_at)) / 60.0) AS avg_min
            FROM public.sessions
            WHERE ended_at IS NOT NULL
              AND started_at >= :since
              AND ended_at <= :now
        """)
        avg_session_minutes = db.execute(q_avg, {"since": since_utc, "now": now_utc}).scalar()
        avg_session_minutes = float(avg_session_minutes) if avg_session_minutes is not None else 0.0

        # 2.3 Sessioni attive ora
        q_active = text("""
            SELECT COUNT(*)::BIGINT AS c
            FROM public.sessions
            WHERE started_at <= :now
              AND (ended_at IS NULL OR ended_at > :now)
        """)
        active_now = db.execute(q_active, {"now": now_utc}).scalar() or 0

        return ok_payload(sessions_last_24h, avg_session_minutes, active_now)
    except Exception as e:
        # Qualunque errore DB torna KPI=0 con nota
        return ok_payload(0, 0.0, 0, note=f"Errore query KPI: {e}")
