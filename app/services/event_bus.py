from __future__ import annotations

from typing import Dict, Any, Optional, List
from datetime import datetime, timezone

from fastapi import BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.models.event_log import EventLog, EventStatus
from app.core.webhook import post_webhook
from app.core.config import settings
from app.schemas.event import validate_event_payload  # ✅ nuova validazione tipizzata


def _utcnow() -> datetime:
    """Ritorna ora UTC con tzinfo per coerenza DB."""
    return datetime.now(timezone.utc)


async def _deliver_event(db: Session, event_log_id: str) -> None:
    """
    Consegna dell'evento:
    - Se ADMIN_WEBHOOK_URL è vuoto/None => no-op success (mark as sent).
    - Altrimenti tenta il post_webhook e aggiorna lo stato.

    Aggiunte:
    - Validazione del payload prima dell'invio (hardening).
    """
    ev: Optional[EventLog] = db.execute(
        select(EventLog).where(EventLog.id == event_log_id)
    ).scalar_one_or_none()

    if ev is None:
        return  # niente da fare

    # Fallback NO-OP SUCCESS se il webhook non è configurato
    webhook_url = (settings.ADMIN_WEBHOOK_URL or "").strip()
    if not webhook_url:
        ev.status = EventStatus.sent
        ev.delivered_at = _utcnow()
        ev.last_error = None
        db.add(ev)
        db.commit()
        return

    # ✅ Hardening: valida il payload (se malformato, marca failed e non inviare)
    try:
        # ensure il campo "type" sia coerente: se manca, lo inseriamo per validazione
        payload_for_validation: Dict[str, Any] = dict(ev.payload or {})
        payload_for_validation.setdefault("type", ev.event_type)
        _ = validate_event_payload(payload_for_validation)
        # Normalizza (opzionale): potremmo salvare la versione validata in futuro
        # validated_payload = _.model_dump()
    except Exception as e:
        ev.status = EventStatus.failed
        ev.retries = (ev.retries or 0) + 1
        ev.last_error = f"validation_error: {e!r}"
        db.add(ev)
        db.commit()
        return

    # Webhook configurato: prova a inviare
    try:
        ok, err = await post_webhook(ev.event_type, ev.payload)
    except Exception as e:
        ok, err = False, f"Unhandled exception: {e!r}"

    if ok:
        ev.status = EventStatus.sent
        ev.delivered_at = _utcnow()
        ev.last_error = None
    else:
        ev.status = EventStatus.failed
        ev.retries = (ev.retries or 0) + 1
        ev.last_error = err

    db.add(ev)
    db.commit()


def schedule_deliver(db: Session, background_tasks: BackgroundTasks, event_log_id: str) -> None:
    """Espone la programmazione della consegna di un evento esistente (riuso da router/admin)."""
    background_tasks.add_task(_deliver_event, db, event_log_id)


def retry_failed_events(
    db: Session,
    background_tasks: BackgroundTasks,
    limit: int = 200,
) -> List[str]:
    """
    Seleziona gli eventi in stato FAILED e li riprogramma per la consegna.
    Ritorna la lista di ID schedulati (max 'limit').
    """
    stmt = (
        select(EventLog.id)
        .where(EventLog.status == EventStatus.failed)
        .order_by(EventLog.created_at.desc())
        .limit(limit)
    )
    ids = [row[0] for row in db.execute(stmt).all()]
    for ev_id in ids:
        background_tasks.add_task(_deliver_event, db, ev_id)
    return ids


def queue_event(
    db: Session,
    background_tasks: BackgroundTasks,
    event_type: str,
    payload: Dict[str, Any],
) -> EventLog:
    """
    Accoda un evento per la consegna asincrona.

    Aggiunte:
    - Validazione tipizzata del payload rispetto a `event_type`.
    - Normalizzazione minima: assicuriamo che `payload["type"]` corrisponda a `event_type`.
    """
    if not event_type or not isinstance(event_type, str):
        raise ValueError("event_type deve essere una stringa non vuota")
    if payload is None or not isinstance(payload, dict):
        raise ValueError("payload deve essere un dict")

    # ✅ Iniettiamo/forziamo la coerenza del campo "type" nel payload
    normalized_payload: Dict[str, Any] = dict(payload)
    normalized_payload["type"] = event_type

    # ✅ Validazione forte prima di salvare e accodare
    try:
        _ = validate_event_payload(normalized_payload)
        # Se in futuro vuoi salvare la versione "pulita":
        # normalized_payload = _.model_dump()
    except Exception as e:
        raise ValueError(f"payload non valido per event_type '{event_type}': {e!r}")

    ev = EventLog(event_type=event_type, payload=normalized_payload, status=EventStatus.queued)
    db.add(ev)
    db.commit()
    db.refresh(ev)

    # Consegna asincrona
    background_tasks.add_task(_deliver_event, db, ev.id)
    return ev
