# app/schemas/session.py
from pydantic import BaseModel
from datetime import datetime
from uuid import UUID

class SessionOut(BaseModel):
    id: UUID
    pin: str
    started_at: datetime
    expires_at: datetime
    max_listeners: int
    is_active: bool

    # Pydantic v2
    model_config = {"from_attributes": True}
