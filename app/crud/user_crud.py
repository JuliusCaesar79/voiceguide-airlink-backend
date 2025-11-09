# app/crud/user_crud.py
from sqlalchemy.orm import Session
from app.models.user import User

def get_by_id(db: Session, user_id: str):
    """
    Restituisce l'utente per ID.
    Compatibile con SQLAlchemy 1.4 e 2.0.
    """
    try:
        # SQLAlchemy 2.0 style (se disponibile)
        return db.get(User, user_id)
    except Exception:
        # Fallback 1.4
        return db.query(User).get(user_id)
