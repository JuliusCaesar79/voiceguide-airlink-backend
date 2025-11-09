from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel

# ===== OVERVIEW =====
class AdminCountByType(BaseModel):
    event_type: str
    count: int

    # Pydantic v2
    model_config = {"from_attributes": True}


class AdminRecentEvent(BaseModel):
    id: str
    event_type: str
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class AdminOverviewOut(BaseModel):
    uptime_hours: float
    events_total: int
    events_failed: int
    events_by_type: List[AdminCountByType]
    recent: List[AdminRecentEvent]

    model_config = {"from_attributes": True}


# ===== LICENSES LISTING =====
class AdminLicenseItem(BaseModel):
    id: str
    key: str
    active: bool
    activated_at: Optional[datetime]
    revoked_at: Optional[datetime]
    assigned_to: Optional[str] = None  # es. guida/owner

    model_config = {"from_attributes": True}


class AdminLicensesOut(BaseModel):
    total: int
    items: List[AdminLicenseItem]

    model_config = {"from_attributes": True}


# ===== ACTIONS =====
class AdminLicenseActionOut(BaseModel):
    id: str
    active: bool
    revoked_at: Optional[datetime]
    message: str

    model_config = {"from_attributes": True}
