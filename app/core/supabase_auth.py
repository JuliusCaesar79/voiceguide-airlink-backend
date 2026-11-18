# app/core/supabase_auth.py
"""
Chi è la guida? (2026-11-18)

L'app manda il token del suo account (Supabase, progetto `itinerarium`) quando
avvia un live. Qui lo si verifica chiedendo a Supabase chi è l'utente: solo così
il live viene legato alla guida vera (serve a "Ricordo del tour", recensioni e
"Segui la guida"). Senza token o con token non valido il live parte lo stesso,
semplicemente senza guida collegata.
"""
from __future__ import annotations

import logging
import os

import requests

logger = logging.getLogger("airlink.supabase_auth")

# Valori pubblici (sono già dentro l'app): si possono sovrascrivere da env.
DEFAULT_SUPABASE_URL = "https://dtbcfjsqwhmdfwkxighr.supabase.co"
DEFAULT_SUPABASE_ANON_KEY = "sb_publishable_6y-VAzI3BJtZe5c9QrEB5w_h18N4DTY"


def user_id_from_bearer(authorization: str | None) -> str | None:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        return None
    base = (os.getenv("SUPABASE_URL") or DEFAULT_SUPABASE_URL).rstrip("/")
    key = os.getenv("SUPABASE_ANON_KEY") or DEFAULT_SUPABASE_ANON_KEY
    try:
        r = requests.get(
            f"{base}/auth/v1/user",
            headers={"apikey": key, "Authorization": f"Bearer {token}"},
            timeout=8,
        )
    except Exception as e:
        logger.warning("Supabase non raggiungibile: %s", e)
        return None
    if r.status_code != 200:
        return None
    uid = (r.json() or {}).get("id")
    return str(uid) if uid else None
