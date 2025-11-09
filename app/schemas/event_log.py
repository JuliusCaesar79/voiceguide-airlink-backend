from typing import Any, Dict, Optional, List, Literal
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field
from app.models.event_log import EventStatus


class EventLogOut(BaseModel):
    id: UUID
    event_type: str
    status: EventStatus
    retries: int = 0
    created_at: datetime
    delivered_at: Optional[datetime] = None
    last_error: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)

    model_config = {"from_attributes": True}


class EventsListOut(BaseModel):
    items: List[EventLogOut]
    count: int

    model_config = {"from_attributes": True}


class EventsQuery(BaseModel):
    status: Optional[EventStatus] = None
    event_type: Optional[str] = None
    since: Optional[datetime] = None
    until: Optional[datetime] = None
    limit: int = 50
    offset: int = 0
    order: Literal["asc", "desc"] = "desc"

    model_config = {"from_attributes": True}


class RetryResultOut(BaseModel):
    retried_count: int
    scheduled_ids: List[UUID]  # <-- accetta UUID
    limit: int

    model_config = {"from_attributes": True}
