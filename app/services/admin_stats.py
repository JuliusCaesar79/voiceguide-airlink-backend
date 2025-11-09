# app/services/admin_stats.py
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models.event import Event
from app.schemas.admin import AdminOverviewOut, AdminCountByType, AdminRecentEvent

APP_STARTED_AT = datetime.now(timezone.utc)

def build_overview(db: Session) -> AdminOverviewOut:
    now = datetime.now(timezone.utc)
    uptime_hours = round((now - APP_STARTED_AT).total_seconds() / 3600, 2)

    # Rileva colonne disponibili del modello Event
    cols = {c.name for c in Event.__table__.columns}
    has_status = "status" in cols
    # Possibili nomi alternativi del tipo evento
    type_field = (
        "event_type" if "event_type" in cols else
        ("type" if "type" in cols else None)
    )
    has_created_at = "created_at" in cols

    # Totali
    events_total = db.query(func.count(Event.id)).scalar() or 0

    # Fallimenti
    if has_status:
        events_failed = (
            db.query(func.count(Event.id))
            .filter(getattr(Event, "status").in_(["error", "failed", "timeout"]))
            .scalar()
            or 0
        )
    else:
        events_failed = 0

    # Distribuzione per tipo (se il campo esiste)
    events_by_type = []
    if type_field:
        rows = (
            db.query(getattr(Event, type_field), func.count(Event.id))
            .group_by(getattr(Event, type_field))
            .all()
        )
        events_by_type = [
            AdminCountByType(event_type=(t or "unknown"), count=c) for t, c in rows
        ]

    # Ultimi eventi (max 10)
    q = db.query(Event)
    if has_created_at:
        q = q.order_by(getattr(Event, "created_at").desc())
    else:
        q = q.order_by(getattr(Event, "id").desc())
    recent_rows = q.limit(10).all()

    recent = []
    for e in recent_rows:
        etype = getattr(e, type_field, None) if type_field else None
        recent.append(
            AdminRecentEvent(
                id=str(e.id),
                event_type=etype or "unknown",
                status=getattr(e, "status", "ok") if has_status else "ok",
                created_at=getattr(e, "created_at", now) if has_created_at else now,
            )
        )

    return AdminOverviewOut(
        uptime_hours=uptime_hours,
        events_total=events_total,
        events_failed=events_failed,
        events_by_type=events_by_type,
        recent=recent,
    )
