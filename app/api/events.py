# app/api/events.py
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional, Any, Dict
from datetime import datetime
import csv
import io

from app.db.session import get_db

# (Lista eventi "operativi" già esistente)
from app.models.event import Event
from app.schemas.event import EventOut, validate_event_payload  # validazione tipizzata

# Persistenza log webhook (nuovo service)
from app.services.event_store import store_received_event, query_events

# Verifica lato receiver (HMAC + timestamp)
from app.core.webhook_verify import verify_hmac_signature
from app.core.config import settings

# Model del registro eventi (per le stats aggregate)
from app.models.event_log import EventLog

router = APIRouter(tags=["events"])


@router.get("/events", response_model=List[EventOut])
def list_events(
    limit: int = Query(200, ge=1, le=1000, description="Numero massimo di eventi da restituire"),
    type: Optional[str] = Query(None, description="Filtra per tipo evento (es. session_started, listener_joined...)"),
    session_id: Optional[str] = Query(None, description="Filtra per ID sessione"),
    since: Optional[str] = Query(None, description="Filtra per eventi successivi a una data ISO8601"),
    db: Session = Depends(get_db),
):
    """
    Restituisce la lista degli eventi (più recenti per primi).
    Supporta filtri per tipo, sessione e data minima (since).
    """
    q = db.query(Event)

    if type:
        q = q.filter(Event.type == type)

    if session_id:
        q = q.filter(Event.session_id == session_id)

    if since:
        try:
            since_dt = datetime.fromisoformat(since)
            q = q.filter(Event.created_at >= since_dt)
        except ValueError:
            pass

    q = q.order_by(Event.created_at.desc()).limit(limit)
    return q.all()


# ----------------------------------------------------------------------
# Receiver webhook firmati:
# - Verifica HMAC + anti-replay
# - Valida payload tipizzato
# - Persistenza su tabella event_log
# ----------------------------------------------------------------------
@router.post("/events/receive", status_code=status.HTTP_204_NO_CONTENT)
async def receive_event(request: Request, db: Session = Depends(get_db)) -> Response:
    """
    Riceve un evento via webhook:
    - Verifica timestamp e firma HMAC.
    - Valida il JSON e il payload contro gli schemi.
    - Salva su DB (event_log) e ritorna 204 se ok.
    """
    raw = await request.body()

    secret = (
        getattr(settings, "WEBHOOK_HMAC_SECRET", None)
        or getattr(settings, "ADMIN_WEBHOOK_SECRET", None)
    )
    if not secret:
        return Response("receiver secret not configured", status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)

    max_age = int(getattr(settings, "WEBHOOK_HMAC_MAX_AGE", 300))
    ok, _evt_header, err = verify_hmac_signature(
        body_bytes=raw,
        headers=request.headers,
        secret=str(secret),
        max_age_seconds=max_age,
    )
    if not ok:
        return Response(f"invalid signature: {err}", status_code=status.HTTP_400_BAD_REQUEST)

    try:
        data: Dict[str, Any] = await request.json()
    except Exception:
        return Response("invalid json", status_code=status.HTTP_400_BAD_REQUEST)

    event_type = data.get("event_type")
    payload = data.get("payload")

    if not isinstance(event_type, str) or not isinstance(payload, dict):
        return Response(
            "invalid body: expected {'event_type': str, 'payload': dict}",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    payload_for_validation: Dict[str, Any] = dict(payload)
    payload_for_validation.setdefault("type", event_type)
    try:
        _validated = validate_event_payload(payload_for_validation)
        # payload_for_validation = _validated.model_dump()  # se vuoi normalizzare
    except Exception as e:
        return Response(f"invalid payload: {e}", status_code=status.HTTP_400_BAD_REQUEST)

    try:
        store_received_event(db, payload_for_validation)
    except Exception as e:
        return Response(f"db error: {e}", status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)

    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ----------------------------------------------------------------------
# Export CSV degli event_log (per analisi/backup)
# ----------------------------------------------------------------------
@router.get("/events/export.csv")
def export_events_csv(
    type: Optional[str] = Query(None, description="Filtra per tipo"),
    session_id: Optional[str] = Query(None, description="Filtra per ID sessione"),
    since: Optional[str] = Query(None, description="ISO8601: da questa data/ora inclusa"),
    to: Optional[str] = Query(None, description="ISO8601: fino a questa data/ora esclusa"),
    include_payload: bool = Query(False, description="Se true, aggiunge la colonna payload"),
    limit: int = Query(10000, ge=1, le=200000, description="Numero max di righe nel CSV"),
    db: Session = Depends(get_db),
):
    """
    Esporta gli eventi dal registro `event_log` in CSV.
    Colonne base: created_at, type, session_id, listener_id, status
    Opzionale: payload (JSON compatto)
    """
    def parse_dt(s: Optional[str]) -> Optional[datetime]:
        if not s:
            return None
        try:
            return datetime.fromisoformat(s)
        except ValueError:
            return None

    rows_q = query_events(
        db,
        type=type,
        session_id=session_id,
        since=parse_dt(since),
        to=parse_dt(to),
    )

    rows = rows_q.limit(limit)

    buf = io.StringIO()
    writer = csv.writer(buf)

    header = ["created_at", "type", "session_id", "listener_id", "status"]
    if include_payload:
        header.append("payload")
    writer.writerow(header)

    import json
    for r in rows:
        row = [
            r.created_at.isoformat() if r.created_at else "",
            r.type or "",
            str(r.session_id) if r.session_id else "",
            str(r.listener_id) if r.listener_id else "",
            r.status or "",
        ]
        if include_payload:
            payload_str = json.dumps(r.payload, separators=(",", ":"), ensure_ascii=False)
            row.append(payload_str)
        writer.writerow(row)

    data = buf.getvalue()
    headers = {
        "Content-Type": "text/csv; charset=utf-8",
        "Content-Disposition": 'attachment; filename="events.csv"',
    }
    return Response(content=data, headers=headers, media_type="text/csv")


# ----------------------------------------------------------------------
# Stats: conteggi per tipo nel range, totale e ultimi eventi
# ----------------------------------------------------------------------
@router.get("/events/stats")
def events_stats(
    since: Optional[str] = Query(None, description="ISO8601: da questa data/ora inclusa"),
    to: Optional[str] = Query(None, description="ISO8601: fino a questa data/ora esclusa"),
    limit_recent: int = Query(10, ge=0, le=100, description="Quanti eventi recenti includere"),
    db: Session = Depends(get_db),
):
    """
    Statistiche semplici sul registro event_log:
    - totale eventi nel range
    - conteggi per 'type'
    - ultimi N eventi (solo campi principali)
    """
    def parse_dt(s: Optional[str]) -> Optional[datetime]:
        if not s:
            return None
        try:
            return datetime.fromisoformat(s)
        except ValueError:
            return None

    since_dt = parse_dt(since)
    to_dt = parse_dt(to)

    base = db.query(EventLog)
    if since_dt:
        base = base.filter(EventLog.created_at >= since_dt)
    if to_dt:
        base = base.filter(EventLog.created_at < to_dt)

    total = base.count()

    by_type_rows = (
        db.query(EventLog.type, func.count())
        .filter(
            (EventLog.created_at >= since_dt) if since_dt else True,
            (EventLog.created_at < to_dt) if to_dt else True,
        )
        .group_by(EventLog.type)
        .all()
    )
    by_type = {t or "unknown": c for (t, c) in by_type_rows}

    recent_q = base.order_by(EventLog.created_at.desc())
    if limit_recent > 0:
        recent_q = recent_q.limit(limit_recent)
    recent = [
        {
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "type": r.type,
            "session_id": str(r.session_id) if r.session_id else None,
            "listener_id": str(r.listener_id) if r.listener_id else None,
            "status": r.status,
        }
        for r in recent_q
    ]

    return {
        "range": {
            "from": since_dt.isoformat() if since_dt else None,
            "to": to_dt.isoformat() if to_dt else None,
        },
        "total": total,
        "by_type": by_type,
        "recent": recent,
    }


# ----------------------------------------------------------------------
# Serie a bucket temporale (per grafici): hour|day
# ----------------------------------------------------------------------
@router.get("/events/stats/series")
def events_stats_series(
    bucket: str = Query("day", pattern="^(hour|day)$", description="Intervallo di aggregazione"),
    since: Optional[str] = Query(None, description="ISO8601: da questa data/ora inclusa"),
    to: Optional[str] = Query(None, description="ISO8601: fino a questa data/ora esclusa"),
    limit_buckets: int = Query(30, ge=1, le=1000, description="Limite massimo di bucket"),
    db: Session = Depends(get_db),
):
    """
    Restituisce serie aggregate per bucket temporale:
    - total: conteggio totale per bucket
    - by_type: conteggio per tipo per bucket
    NB: usa timezone del DB (spesso UTC); se serve tz locale, lo aggiungiamo dopo.
    """
    def parse_dt(s: Optional[str]) -> Optional[datetime]:
        if not s:
            return None
        try:
            return datetime.fromisoformat(s)
        except ValueError:
            return None

    since_dt = parse_dt(since)
    to_dt = parse_dt(to)

    # date_trunc('hour'|'day', created_at)
    dt_bucket = func.date_trunc(bucket, EventLog.created_at).label("t")

    base = db.query(dt_bucket, EventLog.type, func.count().label("c"))
    if since_dt:
        base = base.filter(EventLog.created_at >= since_dt)
    if to_dt:
        base = base.filter(EventLog.created_at < to_dt)

    rows = (
        base.group_by(dt_bucket, EventLog.type)
            .order_by(dt_bucket.desc())
            .limit(limit_buckets * 10)  # margine per tipi multipli
            .all()
    )

    # Collassa in struttura: per timestamp -> { total, by_type{...} }
    buckets = {}
    for t, typ, c in rows:
        key = t.isoformat()
        if key not in buckets:
            buckets[key] = {"t": key, "total": 0, "by_type": {}}
        buckets[key]["total"] += int(c)
        buckets[key]["by_type"][typ or "unknown"] = int(c)

    # Ordina crescente nel tempo e taglia ai limiti richiesti
    series = sorted(buckets.values(), key=lambda x: x["t"])
    if len(series) > limit_buckets:
        series = series[-limit_buckets:]

    return {
        "range": {
            "from": since_dt.isoformat() if since_dt else None,
            "to": to_dt.isoformat() if to_dt else None,
            "bucket": bucket,
        },
        "series": series,
    }
