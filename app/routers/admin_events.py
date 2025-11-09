from typing import Optional, List
from fastapi import APIRouter, Depends, BackgroundTasks, Query
from sqlalchemy.orm import Session
from sqlalchemy import select, and_, func

from app.db.session import get_db
from app.models.event_log import EventLog, EventStatus
from app.schemas.event_log import EventsListOut, EventLogOut, RetryResultOut
from app.services import event_bus

router = APIRouter(prefix="/api/admin/events", tags=["admin:events"])

def _build_filters(
    status: Optional[EventStatus],
    event_type: Optional[str],
    since: Optional[str],
    until: Optional[str],
):
    filters = []
    if status:
        filters.append(EventLog.status == status)
    if event_type:
        filters.append(EventLog.event_type == event_type)
    if since:
        filters.append(EventLog.created_at >= since)
    if until:
        filters.append(EventLog.created_at <= until)
    return and_(*filters) if filters else None

@router.get("", response_model=EventsListOut)
def list_events(
    db: Session = Depends(get_db),
    status: Optional[EventStatus] = Query(default=None),
    event_type: Optional[str] = Query(default=None),
    since: Optional[str] = Query(default=None, description="ISO datetime"),
    until: Optional[str] = Query(default=None, description="ISO datetime"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
):
    """
    Elenco eventi con filtri opzionali.
    """
    filt = _build_filters(status, event_type, since, until)

    base_stmt = select(EventLog)
    if filt is not None:
        base_stmt = base_stmt.where(filt)

    # Count
    count_stmt = select(func.count()).select_from(EventLog)
    if filt is not None:
        count_stmt = count_stmt.where(filt)
    total = db.execute(count_stmt).scalar() or 0

    # Page
    order_col = EventLog.created_at.asc() if order == "asc" else EventLog.created_at.desc()
    page_stmt = base_stmt.order_by(order_col).offset(offset).limit(limit)
    items = [EventLogOut.model_validate(row[0]) for row in db.execute(page_stmt).all()]

    return {"items": items, "count": total}


@router.post("/retry-failed", response_model=RetryResultOut)
def retry_failed(
    background_tasks: BackgroundTasks,
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """
    Riprogramma l'invio per gli eventi in stato FAILED (fino a 'limit').
    Ritorna gli ID schedulati.
    """
    ids = event_bus.retry_failed_events(db, background_tasks, limit=limit)
    return {"retried_count": len(ids), "scheduled_ids": ids, "limit": limit}
