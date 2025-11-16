# app/core/session_end.py
from __future__ import annotations

from datetime import datetime
from typing import Optional, Callable, Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.session import Session as SessionModel
from app.models.listener import Listener as ListenerModel


# Tipo generico per un eventuale logger esterno di eventi
# (es. app.core.utils.log_event). Lo passiamo dall'esterno per non
# vincolare questa logica a una firma specifica.
EventLogger = Callable[..., Any]


def _disconnect_listener(listener: ListenerModel) -> bool:
    """
    Disconnette un singolo listener se ancora collegato.

    Ritorna True se è stato effettivamente modificato, False altrimenti.
    """
    if not listener.is_connected:
        return False

    # Usiamo il metodo helper definito sul modello
    listener.disconnect()
    return True


def end_session_logic(
    db: Session,
    session_id: UUID,
    *,
    reason: str = "auto",
    event_logger: Optional[EventLogger] = None,
) -> Optional[SessionModel]:
    """
    Logica centralizzata per chiudere una sessione VoiceGuide AirLink.

    - Idempotente: se la sessione è già chiusa, non esplode.
    - Marca la sessione come non attiva e imposta ended_at.
    - Disconnette tutti i listener ancora collegati.
    - Opzionalmente logga eventi (session_ended, listener_left)
      tramite una funzione di logging esterna (event_logger).

    Parametri:
        db          : Sessione DB SQLAlchemy aperta.
        session_id  : UUID della sessione da chiudere.
        reason      : "auto" | "manual" | qualsiasi stringa descrittiva.
        event_logger: callable opzionale per loggare eventi.
                      Esempio atteso (da passare dall'esterno):
                      log_event(db=db, event_type="...", session_id=..., description="...")

    Ritorna:
        - SessionModel aggiornato se la sessione esiste
        - None se la sessione non esiste
    """
    session: Optional[SessionModel] = (
        db.query(SessionModel)
        .filter(SessionModel.id == session_id)
        .first()
    )

    if session is None:
        # Nessuna sessione con questo ID: non facciamo nulla.
        return None

    now = datetime.utcnow()

    # ------------------------------------------------------------------
    # 1) Se la sessione è già chiusa, rendiamo comunque coerenti i listener
    # ------------------------------------------------------------------
    if not session.is_active and session.ended_at is not None:
        listeners_modified = 0
        for listener in session.listeners:
            if _disconnect_listener(listener):
                listeners_modified += 1
                if event_logger:
                    try:
                        event_logger(
                            db=db,
                            event_type="listener_left",
                            session_id=session.id,
                            description=f"listener_id={listener.id} (late sync)",
                        )
                    except Exception:
                        # Non blocchiamo mai la logica principale per errori di logging
                        pass

        if listeners_modified > 0:
            db.commit()
            db.refresh(session)

        return session

    # ------------------------------------------------------------------
    # 2) Chiusura sessione "normale"
    # ------------------------------------------------------------------
    session.is_active = False
    session.ended_at = now

    # Disconnettiamo tutti i listener ancora collegati
    for listener in session.listeners:
        if _disconnect_listener(listener):
            if event_logger:
                try:
                    event_logger(
                        db=db,
                        event_type="listener_left",
                        session_id=session.id,
                        description=f"listener_id={listener.id};reason=session_{reason}",
                    )
                except Exception:
                    # Il logging non deve mai impedire la chiusura
                    pass

    # Evento principale: sessione terminata
    if event_logger:
        try:
            event_logger(
                db=db,
                event_type="session_ended",
                session_id=session.id,
                description=f"reason={reason}",
            )
        except Exception:
            # Anche qui: se c'è un errore di logging, non blocchiamo
            pass

    db.commit()
    db.refresh(session)

    return session


def close_all_expired_sessions(
    db: Session,
    *,
    now: Optional[datetime] = None,
    event_logger: Optional[EventLogger] = None,
) -> int:
    """
    Utility da usare nel job periodico:
    - Cerca tutte le sessioni attive e scadute (expires_at <= now)
    - Le chiude usando end_session_logic
    - Ritorna il numero di sessioni effettivamente chiuse

    Questo è pensato per essere usato da:
        - scheduler/background task (auto-close)
        - eventuale comando admin/manuale.
    """
    if now is None:
        now = datetime.utcnow()

    # Trova tutte le sessioni ancora attive ma scadute
    candidates = (
        db.query(SessionModel)
        .filter(
            SessionModel.is_active.is_(True),
            SessionModel.expires_at <= now,
        )
        .all()
    )

    closed_count = 0

    for s in candidates:
        # end_session_logic è idempotente ma qui sappiamo che sono "attive"
        result = end_session_logic(
            db=db,
            session_id=s.id,
            reason="auto",
            event_logger=event_logger,
        )
        if result is not None:
            closed_count += 1

    return closed_count
