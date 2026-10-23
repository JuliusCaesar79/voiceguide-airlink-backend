# app/routers/admin_agora.py
import os
from typing import Optional, List

import requests
from requests.auth import HTTPBasicAuth
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel, Field

router = APIRouter(prefix="/admin/agora", tags=["Admin Agora"])

AGORA_API_BASE = "https://api.agora.io/dev/v1/kicking-rule"
AGORA_CHANNEL_USER_BASE = "https://api.agora.io/dev/v1/channel/user"


def _require_admin(x_admin_key: Optional[str]):
    expected = os.getenv("ADMIN_API_KEY") or os.getenv("ADMIN_KEY")
    if expected and x_admin_key != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")


def _agora_env():
    app_id = os.getenv("AGORA_APP_ID")
    customer_id = os.getenv("AGORA_CUSTOMER_ID")
    customer_secret = os.getenv("AGORA_CUSTOMER_SECRET")
    if not app_id or not customer_id or not customer_secret:
        raise HTTPException(status_code=500, detail="Missing Agora env vars")
    return app_id, customer_id, customer_secret


def _post_kicking_rule(payload: dict):
    app_id, customer_id, customer_secret = _agora_env()
    payload = {"appid": app_id, **payload}

    r = requests.post(
        AGORA_API_BASE,
        json=payload,
        auth=HTTPBasicAuth(customer_id, customer_secret),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        timeout=20,
    )
    return r.status_code, r.text


# ============================================================
# INTERNAL SERVICE (no admin key required, best-effort caller)
# ============================================================
def disband_channel_internal(
    *,
    cname: str,
    time: int = 60,
    privileges: Optional[List[str]] = None,
):
    """
    Disband server-side del canale Agora, da usare internamente (Kill Switch).
    Non richiede header admin perché NON è un endpoint: è una funzione interna.
    """
    if not cname or not str(cname).strip():
        raise ValueError("cname is required")

    if privileges is None:
        privileges = ["join_channel"]

    status_code, text = _post_kicking_rule(
        {
            "cname": str(cname).strip(),
            "time": int(time),
            "privileges": privileges,
        }
    )
    return {"status_code": status_code, "body": text}


def channel_audience_count_internal(*, cname: str, timeout: float = 3.0) -> Optional[int]:
    """
    Numero di ospiti (audience) collegati in questo momento al canale Agora.

    Agora toglie da solo dal canale chi chiude l'app o perde la rete (dopo
    ~20 s), quindi questo conteggio è affidabile anche per le versioni
    dell'app che non avvisano il backend quando l'ospite esce.

    Ritorna 0 se il canale non esiste ancora (nessuno collegato) e None se
    Agora non risponde o mancano le credenziali: il chiamante deve allora
    usare il conteggio del DB. Non solleva mai eccezioni.
    """
    try:
        app_id = os.getenv("AGORA_APP_ID")
        customer_id = os.getenv("AGORA_CUSTOMER_ID")
        customer_secret = os.getenv("AGORA_CUSTOMER_SECRET")
        if not app_id or not customer_id or not customer_secret or not cname:
            return None

        r = requests.get(
            f"{AGORA_CHANNEL_USER_BASE}/{app_id}/{str(cname).strip()}",
            auth=HTTPBasicAuth(customer_id, customer_secret),
            headers={"Accept": "application/json"},
            timeout=timeout,
        )
        if r.status_code != 200:
            return None

        body = r.json()
        if not body.get("success"):
            return None
        data = body.get("data") or {}
        if not data.get("channel_exist"):
            return 0

        # Profilo LIVE_BROADCASTING (quello usato dall'app): la guida è
        # broadcaster, gli ospiti sono audience
        if "audience_total" in data:
            return int(data["audience_total"])
        if "audience" in data:
            return len(data["audience"])
        return None
    except Exception:
        return None


class KickUserBody(BaseModel):
    cname: str = Field(..., min_length=1)
    uid: int = Field(..., ge=1)  # UID numerico Agora
    time: int = Field(0, ge=0, description="0 = kick immediato (no ban persistente)")
    privileges: List[str] = Field(default_factory=lambda: ["join_channel"])


class DisbandChannelBody(BaseModel):
    cname: str = Field(..., min_length=1)
    time: int = Field(60, ge=0, description="Secondi in cui il canale non deve essere riavviato")
    privileges: List[str] = Field(default_factory=lambda: ["join_channel"])


@router.get("/ping")
def ping(x_admin_key: Optional[str] = Header(default=None, alias="X-Admin-Key")):
    _require_admin(x_admin_key)
    return {"ok": True}


@router.post("/kick-user")
def kick_user(
    body: KickUserBody,
    x_admin_key: Optional[str] = Header(default=None, alias="X-Admin-Key"),
):
    _require_admin(x_admin_key)

    status_code, text = _post_kicking_rule(
        {
            "cname": body.cname,
            "uid": body.uid,
            "time": body.time,
            "privileges": body.privileges,
        }
    )
    return {"status_code": status_code, "body": text}


@router.post("/disband-channel")
def disband_channel(
    body: DisbandChannelBody,
    x_admin_key: Optional[str] = Header(default=None, alias="X-Admin-Key"),
):
    _require_admin(x_admin_key)

    status_code, text = _post_kicking_rule(
        {
            "cname": body.cname,
            "time": body.time,
            "privileges": body.privileges,
        }
    )
    return {"status_code": status_code, "body": text}