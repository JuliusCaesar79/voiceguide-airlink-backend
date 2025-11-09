from __future__ import annotations
from datetime import datetime
from typing import Optional, Literal, Dict, Type, Any
from pydantic import BaseModel, Field, UUID4
from uuid import UUID

# -------------------------------------------------------------
#  Schema base per output esistente
# -------------------------------------------------------------
class EventOut(BaseModel):
    id: UUID
    type: str
    description: Optional[str] = None
    session_id: Optional[UUID] = None
    created_at: datetime

    # Pydantic v2
    model_config = {"from_attributes": True}


# -------------------------------------------------------------
#  Nuovi schemi tipizzati per validazione payload (Step A1)
# -------------------------------------------------------------
EventType = Literal[
    "session_started",
    "listener_joined",
    "session_ended",
    "delivery_sent",
    "delivery_failed",
]

class BaseEvent(BaseModel):
    id: UUID4 = Field(..., description="Event UUID")
    type: EventType
    created_at: datetime


class SessionStarted(BaseEvent):
    type: Literal["session_started"]
    session_id: UUID4
    pin: str = Field(..., min_length=6, max_length=6)


class ListenerJoined(BaseEvent):
    type: Literal["listener_joined"]
    session_id: UUID4
    listener_id: UUID4


class SessionEnded(BaseEvent):
    type: Literal["session_ended"]
    session_id: UUID4
    duration_seconds: int = Field(..., ge=0)


class DeliverySent(BaseEvent):
    type: Literal["delivery_sent"]
    event_log_id: UUID4
    target_url: str


class DeliveryFailed(BaseEvent):
    type: Literal["delivery_failed"]
    event_log_id: UUID4
    target_url: str
    reason: str


# -------------------------------------------------------------
#  Registry: mappa tipo_evento → schema corrispondente
# -------------------------------------------------------------
EVENT_SCHEMAS: Dict[str, Type[BaseModel]] = {
    "session_started": SessionStarted,
    "listener_joined": ListenerJoined,
    "session_ended": SessionEnded,
    "delivery_sent": DeliverySent,
    "delivery_failed": DeliveryFailed,
}


# -------------------------------------------------------------
#  Helper per validare dinamicamente un payload evento
# -------------------------------------------------------------
def validate_event_payload(payload: Dict[str, Any]) -> BaseEvent:
    """Verifica che il payload corrisponda a uno schema valido."""
    t = payload.get("type")
    schema = EVENT_SCHEMAS.get(t)
    if not schema:
        raise ValueError(f"Unsupported event type: {t}")
    return schema.model_validate(payload)
