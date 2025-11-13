# app/routers/events_receive.py# app/routers/events_receive.py
from __future__ import annotations

import os, hmac, hashlib, time, json
from typing import Any, Dict, Optional, Tuple
from fastapi import APIRouter, Request, HTTPException, status
from fastapi.responses import Response

# ----------------------------------------------------------------------------
# Config helpers
# ----------------------------------------------------------------------------
def _get_env(name: str, default: Optional[str] = None) -> Optional[str]:
    v = os.getenv(name, default)
    if v is None or (isinstance(v, str) and v.strip() == ""):
        return default
    return v

try:
    from app.core.config import settings  # type: ignore
except Exception:
    settings = None  # fallback

def get_secret() -> str:
    if settings and getattr(settings, "WEBHOOK_HMAC_SECRET", None):
        return settings.WEBHOOK_HMAC_SECRET  # type: ignore
    return _get_env("WEBHOOK_HMAC_SECRET", "prova123")

def get_max_age_seconds() -> int:
    if settings and getattr(settings, "WEBHOOK_HMAC_MAX_AGE", None):
        try:
            return int(settings.WEBHOOK_HMAC_MAX_AGE)  # type: ignore
        except Exception:
            pass
    try:
        return int(_get_env("WEBHOOK_HMAC_MAX_AGE", "300"))
    except Exception:
        return 300

def get_signature_header_name() -> str:
    if settings and getattr(settings, "WEBHOOK_HMAC_HEADER", None):
        return settings.WEBHOOK_HMAC_HEADER  # type: ignore
    return _get_env("WEBHOOK_HMAC_HEADER", "X-Webhook-Signature")

# ----------------------------------------------------------------------------
# Router
# ----------------------------------------------------------------------------
router = APIRouter(prefix="", tags=["events"])  # incluso con prefix /api/events nel main

# ----------------------------------------------------------------------------
# Parsing tollerante header firma
# ----------------------------------------------------------------------------
def _kv_items(header_value: str):
    # Divide per virgola o punto e virgola e normalizza
    for part in header_value.split(","):
        for sub in part.split(";"):
            s = sub.strip()
            if not s or "=" not in s:
                continue
            k, v = s.split("=", 1)
            k = k.strip().lower()
            v = v.strip().strip('"').strip("'")
            if k and v:
                yield k, v

def _parse_combined(value: str) -> Tuple[int, str]:
    """
    Header unico, es:
      X-Webhook-Signature: t=<epoch>,v1=<hex>
      X-Webhook-Signature: ts=<epoch>;sig=<hex>
    """
    data: Dict[str, str] = {}
    for k, v in _kv_items(value):
        data[k] = v

    # alias accettati
    ts_key_candidates = ("t", "ts", "time", "timestamp")
    sig_key_candidates = ("v1", "sig", "signature")

    ts_val = next((data[k] for k in ts_key_candidates if k in data), None)
    sig_val = next((data[k] for k in sig_key_candidates if k in data), None)

    if not ts_val or not sig_val:
        raise ValueError(f"signature header malformato (got: {value!r})")

    try:
        ts = int(ts_val)
    except Exception as e:
        raise ValueError(f"timestamp non valido: {ts_val!r}") from e

    sig = sig_val.lower()
    if not (32 <= len(sig) <= 256):
        raise ValueError("signature length non valida")

    return ts, sig

def _parse_dual(ts_value: str, sig_value: str) -> Tuple[int, str]:
    """
    Doppi header, es:
      X-Webhook-Timestamp: <epoch>
      X-Webhook-Signature: v1=<hex>   (o direttamente <hex>)
    """
    try:
        ts = int(ts_value)
    except Exception as e:
        raise ValueError(f"timestamp non valido: {ts_value!r}") from e

    sig = sig_value.strip().strip('"').strip("'")
    # se arriva nel formato v1=... estrai la parte dopo "="
    if "=" in sig:
        try:
            _, sig = sig.split("=", 1)
            sig = sig.strip()
        except Exception:
            pass
    sig = sig.lower()

    if not (32 <= len(sig) <= 256):
        raise ValueError("signature length non valida")

    return ts, sig

def _compute_signature(secret: str, timestamp: int, body: bytes) -> str:
    # Stile Stripe: f"{timestamp}.{body}"
    payload = f"{timestamp}.".encode("utf-8") + body
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()

# ----------------------------------------------------------------------------
# Log eventi (fallback)
# ----------------------------------------------------------------------------
try:
    from app.core.utils import log_event  # type: ignore
except Exception:
    def log_event(event_type: str, payload: Dict[str, Any]) -> None:  # type: ignore
        print(f"[event] {event_type}: {json.dumps(payload, ensure_ascii=False)}")

# ----------------------------------------------------------------------------
# Endpoint — NOTA: path diverso per evitare conflitti con altri router
# ----------------------------------------------------------------------------
@router.post("/receive-hmac", status_code=status.HTTP_204_NO_CONTENT)
async def receive_event(request: Request) -> Response:
    raw_body = await request.body()

    # 1) Prova parsing header combinato (default nostro)
    header_name = get_signature_header_name()  # di solito X-Webhook-Signature
    sig_header  = request.headers.get(header_name)

    ts: Optional[int] = None
    provided_sig: Optional[str] = None

    if sig_header:
        try:
            ts, provided_sig = _parse_combined(sig_header)
        except ValueError:
            # lasceremo la prova con doppi header
            ts, provided_sig = None, None

    # 2) Se non ricavato dal combinato, prova doppi header
    if ts is None or provided_sig is None:
        ts_header  = request.headers.get("X-Webhook-Timestamp") or request.headers.get("X-Timestamp")
        sig_header2 = request.headers.get("X-Webhook-Signature") or request.headers.get("X-Signature")
        if ts_header and sig_header2:
            try:
                ts, provided_sig = _parse_dual(ts_header, sig_header2)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
        else:
            # manca uno dei due
            missing = "X-Webhook-Timestamp" if not ts_header else header_name
            raise HTTPException(status_code=400, detail=f"invalid signature: missing {missing}")

    # 3) Replay protection
    max_age = get_max_age_seconds()
    now = int(time.time())
    if abs(now - ts) > max_age:
        raise HTTPException(status_code=401, detail="signature expired")

    # 4) Verifica HMAC
    secret = get_secret()
    expected_sig = _compute_signature(secret, ts, raw_body)
    if not hmac.compare_digest(provided_sig, expected_sig):
        raise HTTPException(status_code=401, detail="invalid signature")

    # 5) Parse payload e log (non-bloccante)
    try:
        payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except json.JSONDecodeError:
        payload = {"raw": raw_body.decode("utf-8", errors="replace")}

    event_type = payload.get("type") or payload.get("event") or "unknown"
    try:
        log_event(event_type, payload)
    except Exception:
        pass

    return Response(status_code=status.HTTP_204_NO_CONTENT)
