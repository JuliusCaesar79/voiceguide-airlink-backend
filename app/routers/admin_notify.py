# app/routers/admin_notify.py
from __future__ import annotations

import os
from datetime import datetime, timezone
from uuid import UUID
from types import SimpleNamespace
from typing import Optional

from fastapi import APIRouter, Depends, Request, HTTPException, Body
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy import create_engine
from sqlalchemy import text

from app.services.notify import Notifier

router = APIRouter(tags=["Admin Notify"])

# ---------- deps (reali se presenti, altrimenti fallback) ----------
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
    def _dep(request: Request):
        role = request.headers.get("x-debug-role", "admin").lower()
        uid = request.headers.get("x-debug-user-id", "00000000-0000-0000-0000-000000000000")
        try:
            user_id = UUID(uid)
        except Exception:
            raise HTTPException(status_code=400, detail="Header X-Debug-User-Id non valido")
        return SimpleNamespace(id=user_id, role=role)
    return _dep

get_db = _real_get_db or _fallback_get_db()
current_user = _real_current_user or _fallback_current_user()
# -------------------------------------------------------------------

def _ensure_admin(user):
    if getattr(user, "role", None) != "admin":
        raise HTTPException(status_code=403, detail="admin_only")

@router.get("/api/admin/notify/config", summary="Stato configurazione notifiche (admin)")
def notify_config(user=Depends(current_user)):
    _ensure_admin(user)
    return {
        "smtp": {
            "host": os.getenv("SMTP_HOST"),
            "port": os.getenv("SMTP_PORT"),
            "from": os.getenv("SMTP_FROM"),
            "to": os.getenv("SMTP_TO"),
            "tls": os.getenv("SMTP_TLS", "1"),
            "enabled": bool(os.getenv("SMTP_HOST") and os.getenv("SMTP_FROM") and os.getenv("SMTP_TO")),
        },
        "webhook": {
            "url": os.getenv("NOTIFY_WEBHOOK_URL"),
            "enabled": bool(os.getenv("NOTIFY_WEBHOOK_URL")),
        },
    }

@router.post("/api/admin/notify/test", summary="Invia notifica di test (admin)")
def notify_test(user=Depends(current_user)):
    _ensure_admin(user)
    n = Notifier()
    payload = {
        "at": datetime.now(timezone.utc).isoformat(),
        "who": str(user.id),
        "env": os.getenv("ENV", "dev"),
        "msg": "Test di notifica admin",
    }
    sent = n.notify("Admin Test Notification", payload)
    return {"sent": sent, "payload": payload}

@router.post("/api/admin/notify/session-ended", summary="Notifica manuale ultimo session_ended (admin)")
def notify_last_session_ended(db: Session = Depends(get_db), user=Depends(current_user)):
    _ensure_admin(user)

    # trova ultima sessione con ended_at (o ultimo event session_ended)
    ended_at = None
    session_id = None
    listeners = None
    pin = None

    # ended_at da sessions
    if _has_col(db, "sessions", "ended_at"):
        row = db.execute(text("""
            SELECT s.id, s.ended_at, s.pin, s.listeners_count
            FROM sessions s
            WHERE s.ended_at IS NOT NULL
            ORDER BY s.ended_at DESC
            LIMIT 1
        """)).first()
        if row:
            session_id, ended_at, pin, listeners = row

    # fallback da events
    if not ended_at and _table_exists(db, "events"):
        row = db.execute(text("""
            SELECT e.session_id, MAX(e.created_at) AS ended_at
            FROM events e
            WHERE e.type = 'session_ended'
            GROUP BY e.session_id
            ORDER BY ended_at DESC
            LIMIT 1
        """)).first()
        if row:
            session_id, ended_at = row
        # listeners da events.payload
        if session_id:
            r2 = db.execute(text("""
                SELECT MAX((e.payload->>'listeners_count')::int) AS lc
                FROM events e
                WHERE e.type = 'session_ended' AND e.session_id = :sid
            """), {"sid": session_id}).first()
            if r2 and r2[0] is not None:
                listeners = int(r2[0])

        # pin (se c'è colonna)
        if session_id and _has_col(db, "sessions", "pin"):
            p = db.execute(text("SELECT pin FROM sessions WHERE id = :sid"), {"sid": session_id}).scalar()
            pin = p

    if not ended_at:
        raise HTTPException(status_code=404, detail="Nessuna sessione terminata trovata")

    n = Notifier()
    payload = {
        "event": "session_ended",
        "session_id": str(session_id),
        "pin": pin,
        "ended_at": ended_at.isoformat() if hasattr(ended_at, "isoformat") else str(ended_at),
        "listeners_count": listeners,
    }
    sent = n.notify("Session Ended", payload)
    return {"sent": sent, "payload": payload}


# --- helpers locali (come negli altri router) ---
def _table_exists(db: Session, table: str) -> bool:
    q = text("SELECT 1 FROM information_schema.tables WHERE table_name = :t LIMIT 1")
    return db.execute(q, {"t": table}).first() is not None

def _has_col(db: Session, table: str, col: str) -> bool:
    q = text("""SELECT 1 FROM information_schema.columns
                WHERE table_name = :t AND column_name = :c LIMIT 1""")
    return db.execute(q, {"t": table, "c": col}).first() is not None
