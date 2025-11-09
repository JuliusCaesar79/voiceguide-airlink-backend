# app/crud/license_crud.py
from typing import Optional, Dict, Any, List
from datetime import timedelta
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.models.license import License
from app.models.session import Session as SessionModel
from app.models.listener import Listener
from app.core.utils import gen_pin, utcnow, compute_expiry
from sqlalchemy.exc import IntegrityError

PIN_GENERATION_TRIES = 6

# =========================
#  LOOKUP / ACTIVATION
# =========================
def get_license_by_code(db: Session, code: str):
    return db.query(License).filter(License.code == code).first()

def activate_license(db: Session, code: str):
    lic = get_license_by_code(db, code)
    if not lic:
        return None, "license_not_found"
    now = utcnow()
    if not lic.is_active:
        lic.is_active = True
        lic.activated_at = now
        db.add(lic)
        db.commit()
        db.refresh(lic)
    # compute remaining minutes
    elapsed = (now - lic.activated_at).total_seconds() / 60.0
    remaining = max(0, int(lic.duration_minutes - elapsed))
    return lic, remaining

# =========================
#  SESSION MANAGEMENT
# =========================
def start_session_for_license(db: Session, license_obj: License, requested_max_listeners: int = None):
    now = utcnow()
    # check license active & not expired
    if not license_obj.is_active or not license_obj.activated_at:
        return None, "license_not_active"
    elapsed = (now - license_obj.activated_at).total_seconds() / 60.0
    if elapsed >= license_obj.duration_minutes:
        license_obj.is_active = False
        db.add(license_obj)
        db.commit()
        return None, "license_expired"

    max_listeners = requested_max_listeners or license_obj.max_listeners
    if max_listeners not in (10, 25, 35, 100):
        return None, "invalid_max_listeners"

    # create unique PIN
    pin = None
    for _ in range(PIN_GENERATION_TRIES):
        candidate = gen_pin(6)
        exists = (
            db.query(SessionModel)
              .filter(SessionModel.pin == candidate, SessionModel.is_active == True)
              .first()
        )
        if not exists:
            pin = candidate
            break
    if not pin:
        return None, "pin_generation_failed"

    expires_at = compute_expiry(now, license_obj.duration_minutes - int(elapsed))

    session = SessionModel(
        license_id=license_obj.id,
        pin=pin,
        started_at=now,
        expires_at=expires_at,
        max_listeners=max_listeners,
        is_active=True,
    )
    db.add(session)
    try:
        db.commit()
        db.refresh(session)
    except IntegrityError:
        db.rollback()
        return None, "db_error"
    return session, None

def join_session_by_pin(db: Session, pin: str, display_name: str = None):
    session = db.query(SessionModel).filter(
        SessionModel.pin == pin, SessionModel.is_active == True
    ).first()
    if not session:
        return None, "session_not_found"
    # check expiry
    now = utcnow()
    if session.expires_at <= now:
        session.is_active = False
        db.add(session)
        db.commit()
        return None, "session_expired"

    listeners_count = db.query(Listener).filter(Listener.session_id == session.id).count()
    if listeners_count >= session.max_listeners:
        return None, "session_full"

    listener = Listener(session_id=session.id, display_name=display_name)
    db.add(listener)
    db.commit()
    db.refresh(listener)
    return listener, None

def end_session(db: Session, session_id):
    s = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not s:
        return False
    s.is_active = False
    db.add(s)
    db.commit()
    return True

# =========================
#  ADMIN HELPERS / ACTIONS
# =========================
def _serialize_license(lic: License) -> Dict[str, Any]:
    """
    Serializza una License usando i campi reali del tuo modello.
    Campi opzionali come revoked_at / assigned_to sono riempiti se esistono.
    """
    data = {
        "id": str(lic.id),
        "key": getattr(lic, "code", None),  # nelle API admin la chiamiamo 'key'
        "active": bool(getattr(lic, "is_active", False)),
        "activated_at": getattr(lic, "activated_at", None),
        "revoked_at": getattr(lic, "revoked_at", None) if hasattr(lic, "revoked_at") else None,
        "assigned_to": None,
    }
    # Se in futuro aggiungi campi tipo 'assigned_to' o 'guide_id', popolali così:
    if hasattr(lic, "assigned_to") and getattr(lic, "assigned_to") is not None:
        data["assigned_to"] = getattr(lic, "assigned_to")
    elif hasattr(lic, "guide_id") and getattr(lic, "guide_id") is not None:
        data["assigned_to"] = str(getattr(lic, "guide_id"))
    return data

def admin_list(
    db: Session,
    q: Optional[str] = None,
    active: Optional[bool] = None,
    revoked: Optional[bool] = None,
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    """
    Elenco licenze per pannello admin con filtri e paginazione.
    Filtri supportati:
      - q: ricerca per code (chiave licenza)
      - active: True/False -> filtra su is_active
      - revoked: True/False -> filtra su revoked_at is not/is null (solo se il campo esiste)
    """
    qry = db.query(License)

    if q:
        like = f"%{q}%"
        # ricerca sul campo 'code' (il tuo modello reale)
        qry = qry.filter(License.code.ilike(like))

    if active is not None:
        qry = qry.filter(License.is_active == active)

    if revoked is not None and hasattr(License, "revoked_at"):
        if revoked:
            qry = qry.filter(License.revoked_at.isnot(None))
        else:
            qry = qry.filter(License.revoked_at.is_(None))

    total = qry.count()

    # Ordine: prima le più “recentemente attivate”, poi per code
    # Se non hai created_at nel modello, evitiamo di ordinarci sopra.
    qry = qry.order_by(License.activated_at.desc().nullslast(), License.code.asc())

    items: List[License] = qry.limit(limit).offset(offset).all()

    return {
        "total": total,
        "items": [_serialize_license(x) for x in items],
    }

def admin_revoke(db: Session, license_id: str) -> Optional[License]:
    """
    Revoca una licenza:
      - imposta is_active = False
      - se esiste il campo revoked_at, lo valorizza a ora UTC
    """
    # SQLAlchemy 1.4 compat: .query(...).get(...)
    lic = db.query(License).get(license_id)
    if not lic:
        return None
    lic.is_active = False
    if hasattr(lic, "revoked_at"):
        lic.revoked_at = utcnow()
    db.add(lic)
    db.commit()
    db.refresh(lic)
    return lic

def admin_reactivate(db: Session, license_id: str) -> Optional[License]:
    """
    Riattiva una licenza:
      - imposta is_active = True
      - opzionale: se esiste revoked_at lo azzera
    """
    lic = db.query(License).get(license_id)
    if not lic:
        return None
    lic.is_active = True
    if hasattr(lic, "revoked_at"):
        lic.revoked_at = None
    db.add(lic)
    db.commit()
    db.refresh(lic)
    return lic
