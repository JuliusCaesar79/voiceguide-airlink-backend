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
from app.schemas.license import LicenseCreate, LicenseOut
from app.models.license import License
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


# ===== CREATE LICENSE =====
@router.post(
    "/licenses",
    response_model=LicenseOut,
    summary="Crea una nuova licenza (admin)",
)
def admin_create_license(
    payload: LicenseCreate,
    db: Session = Depends(get_db),
    _admin = Depends(get_current_admin),
):
    """
    Crea una nuova licenza da pannello admin.

    Flusso tipico:
    1) Chiamo questo endpoint da Swagger con:
       - code: "VG-TEST-0001"
       - max_listeners: 10 / 25 / 35 / 100
       - duration_minutes: es. 240 (4h)
       - is_active: False (default)

    2) Poi attivo la licenza con /api/activate-license.
    3) Infine la uso in /api/start-session dalla app.
    """

    # 1. Valida max_listeners in base al vincolo DB
    if payload.max_listeners not in license_crud.ALLOWED_MAX_LISTENERS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"max_listeners must be one of {sorted(license_crud.ALLOWED_MAX_LISTENERS)}",
        )

    # 2. Evita duplicati sul codice licenza
    existing = license_crud.get_license_by_code(db, payload.code)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="License code already exists",
        )

    # 3. Crea la License ORM
    lic = License(
        code=payload.code,
        max_listeners=payload.max_listeners,
        duration_minutes=payload.duration_minutes,
        is_active=payload.is_active,
    )

    db.add(lic)
    db.commit()
    db.refresh(lic)

    return lic


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
