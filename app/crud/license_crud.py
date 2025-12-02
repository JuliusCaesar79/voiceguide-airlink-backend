# app/crud/license_crud.py
from typing import Optional, Dict, Any, List, Tuple
from datetime import timedelta
from sqlalchemy.orm import Session
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from app.models.license import License
from app.models.session import Session as SessionModel
from app.models.listener import Listener
from app.core.utils import gen_pin, utcnow, compute_expiry
from app.core.session_end import end_session_logic  # NEW: usa la logica centralizzata

PIN_GENERATION_TRIES = 6

# Set coerente con il vincolo DB (ck_license_max_listeners_allowed)
ALLOWED_MAX_LISTENERS = {10, 25, 35, 100}

# =========================
#  LOOKUP / ACTIVATION
# =========================
def get_license_by_code(db: Session, code: str) -> Optional[License]:
    return db.query(License).filter(License.code == code).first()


def activate_license(
    db: Session,
    code: str,
) -> Tuple[Optional[License], Optional[int] | str]:
    """
    Attiva o verifica una licenza e restituisce (License, remaining_minutes).

    Ritorni possibili:
    - (None, "license_not_found") se il codice non esiste.
    - (None, "license_used") se la licenza è già stata usata/consumata.
    - (License, remaining_minutes) in tutti gli altri casi validi.

    Logica:
    - Se la licenza è "fresca" (activated_at is None): prima attivazione → imposta activated_at = now
      e is_active = True, remaining = duration_minutes.
    - Se è già attiva (activated_at non null e is_active True) → calcola remaining in base al tempo trascorso.
    - Se è già attivata ma non più attiva (is_active False) → la consideriamo CONSUMATA
      secondo la regola "una licenza = un tour secco".
    """
    lic = get_license_by_code(db, code)
    if not lic:
        return None, "license_not_found"

    now = utcnow()

    # durata di fallback se il campo non esiste o è null
    duration_minutes = int(getattr(lic, "duration_minutes", 240) or 240)

    activated_at = getattr(lic, "activated_at", None)
    is_active = bool(getattr(lic, "is_active", False))

    # Caso: licenza già attivata in passato ma non più attiva
    # -> per la nostra regola commerciale, la trattiamo come "già usata".
    if activated_at is not None and not is_active:
        return None, "license_used"

    # Prima attivazione: la licenza non era mai stata attivata
    if activated_at is None:
        lic.is_active = True
        if hasattr(lic, "activated_at"):
            lic.activated_at = now
        if hasattr(lic, "updated_at"):
            lic.updated_at = now

        db.add(lic)
        db.commit()
        db.refresh(lic)
        return lic, duration_minutes

    # Caso: licenza già attiva (activated_at valorizzato, is_active True)
    elapsed_minutes = max(0, int((now - activated_at).total_seconds() / 60.0))
    remaining = max(0, duration_minutes - elapsed_minutes)

    # opzionale: aggiorna updated_at
    if hasattr(lic, "updated_at"):
        lic.updated_at = now
        db.add(lic)
        db.commit()
        db.refresh(lic)

    return lic, remaining


# =========================
#  SESSION MANAGEMENT
# =========================
def start_session_for_license(
    db: Session,
    license_obj: License,
    requested_max_listeners: int = None,
):
    """
    Avvia una sessione collegata a una licenza.

    Regole:
    - La licenza deve essere attiva (is_active True) e con activated_at valorizzato.
    - La licenza non deve essere scaduta rispetto a duration_minutes.
    - max_listeners deve rientrare in ALLOWED_MAX_LISTENERS.
    - CREA UNA SOLA SESSIONE PER LICENZA:
      appena viene creata una sessione, la licenza viene marcata come non attiva
      (consumata) secondo la regola "una licenza = un tour secco".
    """
    now = utcnow()

    # check license attiva e marcata come attivata
    if not getattr(license_obj, "is_active", False) or not getattr(license_obj, "activated_at", None):
        return None, "license_not_active"

    duration_minutes = int(getattr(license_obj, "duration_minutes", 240) or 240)
    elapsed = (now - license_obj.activated_at).total_seconds() / 60.0
    if elapsed >= duration_minutes:
        # la licenza è scaduta: la marchiamo come non attiva
        license_obj.is_active = False
        if hasattr(license_obj, "updated_at"):
            license_obj.updated_at = now
        db.add(license_obj)
        db.commit()
        return None, "license_expired"

    # valida max_listeners in base al vincolo DB
    default_ml = int(getattr(license_obj, "max_listeners", 10) or 10)
    max_listeners = int(requested_max_listeners or default_ml)
    if max_listeners not in ALLOWED_MAX_LISTENERS:
        return None, "invalid_max_listeners"

    # Regola commerciale: UNA LICENZA = UN TOUR.
    # Appena creiamo una sessione, marchiamo la licenza come NON ATTIVA
    # in modo che non possa più essere usata per iniziare altri tour.
    license_obj.is_active = False
    if hasattr(license_obj, "updated_at"):
        license_obj.updated_at = now
    db.add(license_obj)

    # genera PIN univoco
    pin = None
    for _ in range(PIN_GENERATION_TRIES):
        candidate = gen_pin(6)
        exists = (
            db.query(SessionModel)
            .filter(SessionModel.pin == candidate, SessionModel.is_active.is_(True))
            .first()
        )
        if not exists:
            pin = candidate
            break
    if not pin:
        return None, "pin_generation_failed"

    remaining_minutes = max(0, int(duration_minutes - int(elapsed)))
    expires_at = compute_expiry(now, remaining_minutes)

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
    session = (
        db.query(SessionModel)
        .filter(SessionModel.pin == pin, SessionModel.is_active.is_(True))
        .first()
    )
    if not session:
        return None, "session_not_found"

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


def end_session(db: Session, session_id: str) -> bool:
    """
    Chiude una sessione utilizzando la logica centralizzata di app.core.session_end.

    - Idempotente: se la sessione non esiste, ritorna False.
    - Se esiste:
        * marca la sessione come non attiva
        * imposta ended_at
        * disconnette tutti i listener ancora collegati

    NOTA: la regola "una licenza = un tour" è già gestita in start_session_for_license,
    dove la licenza viene marcata come non attiva appena il tour parte.
    """
    session = end_session_logic(
        db=db,
        session_id=session_id,
        reason="manual",
        event_logger=None,  # il logging di session_ended viene gestito dal router API
    )
    return session is not None


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
        "key": getattr(lic, "code", None),
        "active": bool(getattr(lic, "is_active", False)),
        "activated_at": getattr(lic, "activated_at", None),
        "revoked_at": getattr(lic, "revoked_at", None) if hasattr(lic, "revoked_at") else None,
        "assigned_to": None,
    }
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
    """
    qry = db.query(License)

    if q:
        like = f"%{q}%"
        qry = qry.filter(License.code.ilike(like))

    if active is not None:
        qry = qry.filter(License.is_active == active)

    if revoked is not None and hasattr(License, "revoked_at"):
        if revoked:
            qry = qry.filter(License.revoked_at.isnot(None))
        else:
            qry = qry.filter(License.revoked_at.is_(None))

    total = qry.count()
    qry = qry.order_by(License.activated_at.desc().nullslast(), License.code.asc())
    items: List[License] = qry.limit(limit).offset(offset).all()

    return {
        "total": total,
        "items": [_serialize_license(x) for x in items],
    }


def admin_revoke(db: Session, license_id: str) -> Optional[License]:
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
