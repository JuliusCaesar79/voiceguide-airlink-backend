# app/schemas/license.py
from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, Field

# ------------------------------------------------------------
# Base schema
# ------------------------------------------------------------
class LicenseBase(BaseModel):
    code: str
    max_listeners: Optional[int] = 40
    duration_minutes: Optional[int] = 60

    model_config = {"from_attributes": True}


# ------------------------------------------------------------
# Create (usato da /api/admin/licenses)
# ------------------------------------------------------------
class LicenseCreate(LicenseBase):
    """Schema per creare una nuova licenza (admin)."""
    is_active: bool = False

    model_config = {"from_attributes": True}


# ------------------------------------------------------------
# Output / lettura
# ------------------------------------------------------------
class LicenseOut(LicenseBase):
    """Schema di risposta per licenze (ORM)."""
    id: UUID
    is_active: bool
    activated_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ------------------------------------------------------------
# Attivazione (già usato da /activate-license)
# ------------------------------------------------------------
class LicenseActivateIn(BaseModel):
    license_code: str

    model_config = {"from_attributes": True}


class LicenseActivateOut(BaseModel):
    id: str
    code: str
    is_active: bool
    activated_at: Optional[datetime] = None
    remaining_minutes: Optional[int] = None

    model_config = {"from_attributes": True}
