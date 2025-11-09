# app/routers/health.py
from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID
from types import SimpleNamespace

from fastapi import APIRouter, Depends, Request, HTTPException
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy import text, create_engine

# Tag uniforme per la sezione di sistema
router = APIRouter(tags=["system"])

# ------------------------------------------------------------
# Avvio modulo (per uptime)
# ------------------------------------------------------------
STARTED_AT = datetime.now(timezone.utc)
APP_VERSION = os.getenv("APP_VERSION", "1.0.0")
SERVICE_NAME = os.getenv("APP_SERVICE", "VoiceGuide AirLink API")

# ---------- deps (usa reali se presenti, altrimenti fallback) ----------
def _wire_real_deps():
    candidates = [
        ("app.dependencies", "get_db", "current_user"),
        ("app.api.dependencies", "get_db", "current_user"),
        ("app.api.deps", "get_db", "current_user"),
        ("app.core.dependencies", "get_db", "current_user"),
    ]
    for mod_name, gdb, cu in candidates:
        try:
            mod = __import__(mod_name, fromlist=[gdb, cu])
            return getattr(mod, gdb), getattr(mod, cu)
        except Exception:
            continue
    return None, None

_real_get_db, _real_current_user = _wire_real_deps()

def _fallback_get_db():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL non configurato")
    engine = create_engine(db_url, future=True)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    def _dep():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()
    return _dep

def _fallback_current_user():
    # usato solo se serve; l'endpoint è pubblico
    def _dep(request: Request):
        role = request.headers.get("x-debug-role", "admin").lower()
        uid = request.headers.get("x-debug-user-id", "00000000-0000-0000-0000-000000000000")
        try:
            _ = UUID(uid)
        except Exception:
            raise HTTPException(status_code=400, detail="Header X-Debug-User-Id non valido")
        return SimpleNamespace(id=uid, role=role)
    return _dep

get_db = _real_get_db or _fallback_get_db()
current_user = _real_current_user or _fallback_current_user()
# ----------------------------------------------------------------------

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

def _db_latency(db: Session) -> float:
    t0 = time.perf_counter()
    db.execute(text("SELECT 1"))
    return round((time.perf_counter() - t0) * 1000.0, 2)  # ms

@router.get(
    "/api/health",
    tags=["system"],
    name="health_check",
    operation_id="health_check",
    summary="Health check avanzato"
)
def health_check(db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    uptime_seconds = int((now - STARTED_AT).total_seconds())

    # Stato DB base
    db_ok = True
    db_error: Optional[str] = None
    db_now: Optional[str] = None
    db_version: Optional[str] = None
    db_latency_ms: Optional[float] = None
    alembic_head: Optional[str] = None

    try:
        db_latency_ms = _db_latency(db)
        db_now = db.execute(text("SELECT NOW() AT TIME ZONE 'UTC' AS now_utc")).scalar()
        db_version = db.execute(text("SELECT version()")).scalar()
        if _table_exists(db, "alembic_version"):
            alembic_head = db.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).scalar()
    except Exception as e:
        db_ok = False
        db_error = str(e)

    # Metriche rapide (solo se ci sono le tabelle)
    sessions_total = events_total = 0
    last_event_at = last_session_started_at = last_session_ended_at = None

    try:
        if _table_exists(db, "events"):
            events_total = db.execute(text("SELECT COUNT(*) FROM events")).scalar() or 0
            last_event_at = db.execute(text("SELECT MAX(created_at) FROM events")).scalar()
        if _table_exists(db, "sessions"):
            sessions_total = db.execute(text("SELECT COUNT(*) FROM sessions")).scalar() or 0

            # last started
            if _has_col(db, "sessions", "started_at"):
                last_session_started_at = db.execute(text("SELECT MAX(started_at) FROM sessions")).scalar()

            # last ended: preferisci colonna, fallback da events
            if _has_col(db, "sessions", "ended_at"):
                last_session_ended_at = db.execute(text("SELECT MAX(ended_at) FROM sessions")).scalar()
            elif _table_exists(db, "events"):
                last_session_ended_at = db.execute(text("""
                    SELECT MAX(e.created_at)
                    FROM events e
                    WHERE e.type = 'session_ended'
                """)).scalar()
    except Exception:
        # metrica non critica: ignora
        pass

    return {
        "status": "ok" if db_ok else "degraded",
        "service": SERVICE_NAME,
        "version": APP_VERSION,
        "started_at": STARTED_AT.isoformat(),
        "uptime_seconds": uptime_seconds,
        "db": {
            "status": "ok" if db_ok else "error",
            "latency_ms": db_latency_ms,
            "now_utc": str(db_now) if db_now is not None else None,
            "db_version": db_version,
            "alembic_head": alembic_head,
            "error": db_error,
        },
        "metrics": {
            "sessions_total": sessions_total,
            "events_total": events_total,
            "last_event_at": last_event_at.isoformat() if last_event_at else None,
            "last_session_started_at": last_session_started_at.isoformat() if last_session_started_at else None,
            "last_session_ended_at": last_session_ended_at.isoformat() if last_session_ended_at else None,
        },
        "env": {
            "git_sha": os.getenv("GIT_SHA"),
            "env": os.getenv("ENV", "dev"),
        },
    }
