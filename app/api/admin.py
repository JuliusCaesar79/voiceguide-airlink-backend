# app/api/admin.py
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.api.deps import get_current_admin
from app.schemas.admin import (
    AdminOverviewOut,
    AdminLicensesOut,
    AdminLicenseActionOut,
)
from app.services import admin_stats
from app.crud import license_crud

# ✅ Prefisso ufficiale definitivo
router = APIRouter(prefix="/api/admin", tags=["admin"])

# ===== OVERVIEW =====
@router.get("/overview", response_model=AdminOverviewOut)
def admin_overview(
    db: Session = Depends(get_db),
    _admin = Depends(get_current_admin),
):
    """
    Panoramica stato sistema: uptime, conteggi eventi, ultimi eventi.
    """
    return admin_stats.build_overview(db)

# ===== LICENSES LIST =====
@router.get("/licenses", response_model=AdminLicensesOut)
def admin_licenses(
    db: Session = Depends(get_db),
    _admin = Depends(get_current_admin),
    q: str | None = Query(None, description="Cerca per chiave licenza"),
    active: bool | None = Query(None, description="Filtra per attive True/False"),
    revoked: bool | None = Query(None, description="Filtra per revocate True/False"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """
    Elenco licenze con filtri e paginazione.
    """
    return license_crud.admin_list(
        db, q=q, active=active, revoked=revoked, limit=limit, offset=offset
    )

# ===== ACTION: REVOKE =====
@router.post("/licenses/{license_id}/revoke", response_model=AdminLicenseActionOut)
def admin_revoke_license(
    license_id: str,
    db: Session = Depends(get_db),
    _admin = Depends(get_current_admin),
):
    """
    Revoca una licenza attiva.
    """
    lic = license_crud.admin_revoke(db, license_id)
    if not lic:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="License not found")
    return AdminLicenseActionOut(
        id=str(lic.id),
        active=bool(getattr(lic, "is_active", False)),
        revoked_at=getattr(lic, "revoked_at", None),
        message="License revoked",
    )

# ===== ACTION: REACTIVATE =====
@router.post("/licenses/{license_id}/reactivate", response_model=AdminLicenseActionOut)
def admin_reactivate_license(
    license_id: str,
    db: Session = Depends(get_db),
    _admin = Depends(get_current_admin),
):
    """
    Riattiva una licenza precedentemente revocata.
    """
    lic = license_crud.admin_reactivate(db, license_id)
    if not lic:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="License not found")
    return AdminLicenseActionOut(
        id=str(lic.id),
        active=bool(getattr(lic, "is_active", False)),
        revoked_at=getattr(lic, "revoked_at", None),
        message="License reactivated",
    )
