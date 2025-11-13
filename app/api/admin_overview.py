# ============================================================
#  VoiceGuide AirLink — Admin Overview Endpoint (robusto)
# ============================================================
# File: app/api/admin_overview.py
# - Accetta X-Admin-Key o X-Admin-Secret
# - Adatta il SELECT alla presenza/assenza di ended_at/expires_at
# ============================================================

from __future__ import annotations
import os
from typing import Any, Dict
from fastapi import APIRouter, Depends, HTTPException, Header, status
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.db.session import get_db

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _check_admin_key(admin_key_header: str | None) -> None:
    expected = os.getenv("ADMIN_KEY") or os.getenv("ADMIN_API_KEY")
    if expected and (not admin_key_header or admin_key_header != expected):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: invalid admin key",
        )


def _col_exists(db: Session, table: str, column: str) -> bool:
    sql = text("""
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = :table AND column_name = :column
        )
    """)
    return bool(db.execute(sql, {"table": table, "column": column}).scalar())


@router.get("/overview")
def admin_overview(
    db: Session = Depends(get_db),
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
    x_admin_secret: str | None = Header(default=None, alias="X-Admin-Secret"),
) -> Dict[str, Any]:
    """
    Riepilogo amministrativo con conteggi e ultime sessioni.
    Accetta header X-Admin-Key o X-Admin-Secret.
    """
    header_val = x_admin_key or x_admin_secret
    _check_admin_key(header_val)

    # Conteggi rapidi
    q = {
        "licenses_total": "SELECT COUNT(*) FROM licenses",
        "licenses_activated": "SELECT COUNT(*) FROM licenses WHERE activated_at IS NOT NULL",
        "sessions_total": "SELECT COUNT(*) FROM sessions",
        "sessions_active": "SELECT COUNT(*) FROM sessions WHERE is_active = TRUE",
        "listeners_total": "SELECT COUNT(*) FROM listeners",
    }

    out: Dict[str, Any] = {"protection": bool(os.getenv("ADMIN_KEY") or os.getenv("ADMIN_API_KEY"))}
    for key, sql in q.items():
        out[key] = db.execute(text(sql)).scalar_one()

    # Determina la colonna "fine sessione" disponibile
    has_ended = _col_exists(db, "sessions", "ended_at")
    has_expires = _col_exists(db, "sessions", "expires_at")

    if has_ended:
        ended_expr = "ended_at"
    elif has_expires:
        ended_expr = "expires_at"
    else:
        ended_expr = "NULL::timestamp"

    # Ultime 10 sessioni (con ended_at 'virtuale' se serve)
    recent_sql = text(f"""
        SELECT id, license_id, started_at, {ended_expr} AS ended_at, is_active, max_listeners
        FROM sessions
        ORDER BY started_at DESC
        LIMIT 10
    """)
    rows = db.execute(recent_sql).mappings().all()
    out["recent_sessions"] = [dict(r) for r in rows]

    return out

# In main.py:
# from app.api.admin_overview import router as admin_overview_router
# app.include_router(admin_overview_router)
