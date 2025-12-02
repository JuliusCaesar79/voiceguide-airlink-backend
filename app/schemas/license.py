# app/schemas/license.py
from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, Field

# ------------------------------------------------------------
# Base schema
# ------------------------------------------------------------
class LicenseBase(BaseModel):
    code: str = Field(..., min_length=3, max_length=64)

    # Tagli consentiti dal vincolo di DB: 10, 25, 35, 100
    max_listeners: int = Field(
        10,
        description="Numero massimo ascoltatori. Valori consentiti: 10, 25, 35, 100."
    )

    # Durata di default allineata al modello: 240 minuti (4h)
    duration_minutes: int = Field(
        240,
        ge=15,
        le=24 * 60,
        description="Durata licenza in minuti (default 240 = 4h)."
    )

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
    # NEW: numero massimo ospiti per questa licenza (mappato da License.max_listeners)
    max_guests: int

    model_config = {"from_attributes": True}
