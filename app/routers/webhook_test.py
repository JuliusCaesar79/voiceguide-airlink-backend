# app/routers/webhook_test.py
from __future__ import annotations

import os
import json
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

# ------------------------------------------------------------
# Notifiche (console/email)
# ------------------------------------------------------------
try:
    from app.services.notify import notify_admin
except Exception:
    def notify_admin(title: str, body: str, payload: dict | None = None):
        print(f"[NOTIFY Fallback] {title} — {body} — {json.dumps(payload or {}, ensure_ascii=False)}")
        return {"status": "fallback", "channel": "console"}

# ------------------------------------------------------------
# Webhook esterno (HTTP POST opzionale)
# ------------------------------------------------------------
try:
    import requests
except Exception:
    requests = None

router = APIRouter(prefix="/api/_test/webhook", tags=["Webhook Test"])

# ------------------------------------------------------------
# DB deps fallback
# ------------------------------------------------------------
def _get_db():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL non configurato nell'ambiente.")
    engine = create_engine(db_url, future=True)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _table_exists(db: Session, table: str) -> bool:
    q = text("SELECT 1 FROM information_schema.tables WHERE table_name=:t LIMIT 1")
    return db.execute(q, {"t": table}).first() is not None


def _has_col(db: Session, table: str, col: str) -> bool:
    q = text("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name=:t AND column_name=:c LIMIT 1
    """)
    return db.execute(q, {"t": table, "c": col}).first() is not None


# ------------------------------------------------------------
# Schemi
# ------------------------------------------------------------
class SessionEndedPayload(BaseModel):
    license_code: Optional[str] = Field(default=None, description="Codice licenza guida")
    session_id: UUID
    listeners_count: Optional[int] = Field(default=None, ge=0)
    ended_at: Optional[datetime] = None


# ------------------------------------------------------------
# Utils
# ------------------------------------------------------------
def _post_admin_webhook(payload: dict) -> dict:
    url = os.getenv("ADMIN_WEBHOOK_URL")
    if not url:
        return {"status": "disabled", "reason": "ADMIN_WEBHOOK_URL not set"}
    if requests is None:
        return {"status": "disabled", "reason": "requests module unavailable"}
    try:
        r = requests.post(url, json=payload, timeout=5)
        return {"status": "ok", "code": r.status_code}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------
@router.get("/ping")
def ping():
    """Verifica lo stato del servizio webhook."""
    return {"ok": True, "service": "webhook", "ts": datetime.utcnow().isoformat()}


@router.post("/session_ended")
def session_ended(payload: SessionEndedPayload, db: Session = Depends(_get_db)):
    """Registra un evento di fine sessione e invia notifiche admin."""
    # Feature detection
    has_sessions = _table_exists(db, "sessions")
    has_events = _table_exists(db, "events")
    if not has_sessions:
        raise HTTPException(status_code=400, detail="sessions table non disponibile")

    sess_has_ended = _has_col(db, "sessions", "ended_at")
    sess_has_status = _has_col(db, "sessions", "status")
    sess_has_listcnt = _has_col(db, "sessions", "listeners_count")
    sess_has_started = _has_col(db, "sessions", "started_at")

    # --------------------------------------------------------
    # 1) Registra evento (se tabella events c'è)
    # --------------------------------------------------------
    if has_events:
        try:
            has_payload_col = _has_col(db, "events", "payload")

            # JSON-safe (UUID, datetime, ecc.)
            payload_dict = jsonable_encoder(payload)
            payload_json = json.dumps(payload_dict, ensure_ascii=False)

            if has_payload_col:
                # Con colonna payload JSONB (PostgreSQL)
                db.execute(
                    text("""
                        INSERT INTO events (type, session_id, license_code, created_at, payload)
                        VALUES ('session_ended', :sid, :lic, :ts, CAST(:payload_json AS JSONB))
                    """),
                    {
                        "sid": str(payload.session_id),
                        "lic": payload.license_code,
                        "ts": payload.ended_at or datetime.utcnow(),
                        "payload_json": payload_json,
                    },
                )
            else:
                # Fallback: nessuna colonna payload
                db.execute(
                    text("""
                        INSERT INTO events (type, session_id, license_code, created_at)
                        VALUES ('session_ended', :sid, :lic, :ts)
                    """),
                    {
                        "sid": str(payload.session_id),
                        "lic": payload.license_code,
                        "ts": payload.ended_at or datetime.utcnow(),
                    },
                )
        except Exception as e:
            # L'errore di logging non deve bloccare il flusso
            print(f"[events insert warning] {e}")

    # --------------------------------------------------------
    # 2) Aggiorna riga sessions (best-effort)
    # --------------------------------------------------------
    sets = []
    params = {"sid": str(payload.session_id)}
    if sess_has_ended:
        sets.append("ended_at = COALESCE(:ended_at, ended_at)")
        params["ended_at"] = payload.ended_at or datetime.utcnow()
    if sess_has_status:
        sets.append("status = 'ended'")
    if sess_has_listcnt and payload.listeners_count is not None:
        sets.append("listeners_count = :lc")
        params["lc"] = payload.listeners_count

    if sets:
        db.execute(text(f"UPDATE sessions SET {', '.join(sets)} WHERE id = :sid"), params)

    db.commit()

    # --------------------------------------------------------
    # 3) Calcola durata (se possibile) — senza referenziare ended_at se non esiste
    # --------------------------------------------------------
    duration_seconds = None
    if sess_has_started:
        params_dur = {"sid": str(payload.session_id), "ended_at": payload.ended_at or datetime.utcnow()}
        if sess_has_ended:
            sql_dur = text("""
                SELECT EXTRACT(EPOCH FROM (COALESCE(ended_at, :ended_at) - started_at))::bigint AS dur
                FROM sessions WHERE id = :sid
            """)
        else:
            sql_dur = text("""
                SELECT EXTRACT(EPOCH FROM (:ended_at - started_at))::bigint AS dur
                FROM sessions WHERE id = :sid
            """)
        row = db.execute(sql_dur, params_dur).first()
        duration_seconds = int(row.dur) if row and row.dur is not None else None

    # --------------------------------------------------------
    # 4) Notifiche admin (console/email)
    # --------------------------------------------------------
    notify_admin(
        title="VoiceGuide • Sessione terminata",
        body=f"Sessione {payload.session_id} conclusa.",
        payload={
            "license_code": payload.license_code,
            "session_id": str(payload.session_id),
            "listeners_count": payload.listeners_count,
            "ended_at": (payload.ended_at or datetime.utcnow()).isoformat(),
            "duration_seconds": duration_seconds,
        },
    )

    # --------------------------------------------------------
    # 5) Webhook esterno opzionale
    # --------------------------------------------------------
    webhook_result = _post_admin_webhook({
        "type": "session_ended",
        "license_code": payload.license_code,
        "session_id": str(payload.session_id),
        "listeners_count": payload.listeners_count,
        "ended_at": (payload.ended_at or datetime.utcnow()).isoformat(),
        "duration_seconds": duration_seconds,
    })

    return {
        "ok": True,
        "updated_columns": {
            "ended_at": sess_has_ended,
            "status": sess_has_status,
            "listeners_count": sess_has_listcnt,
        },
        "duration_seconds": duration_seconds,
        "webhook": webhook_result,
    }
