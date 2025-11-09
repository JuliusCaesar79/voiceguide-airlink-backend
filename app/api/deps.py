# app/api/deps.py
from __future__ import annotations

import os
from types import SimpleNamespace
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core import security          # usa oauth2_scheme e decode_token (dev-safe)
from app.crud import user_crud         # get_by_id per eventuali rotte che usano JWT


# ==========================================================
#  UTENTE CORRENTE (autenticazione JWT standard)
# ==========================================================
def get_current_user(
    token: str = Depends(security.oauth2_scheme),
    db: Session = Depends(get_db),
):
    """
    Estrae l'utente corrente dal token (decodifica payload senza verifica firma).
    Manteniamo questa dipendenza per eventuali rotte non-admin che ne avessero bisogno.
    """
    try:
        payload = security.decode_token(token)  # deve restituire dict con 'sub'
        user_id: str | None = payload.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
            )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    user = user_crud.get_by_id(db, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    return user


# ==========================================================
#  CONTROLLO ADMIN (tramite header segreto)
# ==========================================================
# Accesso alle rotte admin tramite header segreto semplice:
#   X-Admin-Secret: <valore>
# Il valore atteso è ADMIN_SECRET (env) o 'prova123' di default.
# Imposta la variabile d'ambiente prima di avviare il server:
#   PowerShell →  $env:ADMIN_SECRET="IL_TUO_SEGRETO_LUNGO"
#   bash/zsh   →  export ADMIN_SECRET="IL_TUO_SEGRETO_LUNGO"
# ==========================================================
def get_current_admin(
    x_admin_secret: str | None = Header(None, alias="X-Admin-Secret"),
):
    ADMIN_SECRET = os.getenv("ADMIN_SECRET", "prova123")

    if x_admin_secret and x_admin_secret == ADMIN_SECRET:
        # finto utente admin (namespace) per compatibilità con dipendenze a valle
        return SimpleNamespace(id="dev-admin", role="admin", is_admin=True)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated (missing or invalid X-Admin-Secret)",
    )
