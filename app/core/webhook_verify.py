# app/core/webhook_verify.py
from __future__ import annotations
import hmac
import hashlib
import time
from typing import Tuple, Optional

# Devono combaciare con quelli usati dal sender
DEFAULT_HEADER_SIG = "X-Webhook-Signature"
DEFAULT_HEADER_TS  = "X-Webhook-Timestamp"
DEFAULT_HEADER_EVT = "X-Webhook-Event"
DEFAULT_ALGO       = "sha256"
DEFAULT_MAX_AGE_S  = 300  # 5 minuti anti-replay

def verify_hmac_signature(
    body_bytes: bytes,
    headers: dict,
    secret: str,
    header_sig: str = DEFAULT_HEADER_SIG,
    header_ts: str = DEFAULT_HEADER_TS,
    algo: str = DEFAULT_ALGO,
    max_age_seconds: int = DEFAULT_MAX_AGE_S,
) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Verifica timestamp e firma HMAC (anti-replay).
    La firma è calcolata su:  f"{timestamp}.{body_bytes}"

    Ritorna:
      (ok: bool, event_type: Optional[str], error: Optional[str])
    """
    ts = headers.get(header_ts)
    if not ts:
        return False, None, f"missing {header_ts}"

    try:
        ts_int = int(ts)
    except Exception:
        return False, None, "invalid timestamp"

    now = int(time.time())
    if abs(now - ts_int) > max_age_seconds:
        return False, None, "stale or future timestamp"

    sig_recv = headers.get(header_sig)
    if not sig_recv:
        return False, None, f"missing {header_sig}"

    if not hasattr(hashlib, algo):
        return False, None, f"unsupported algo {algo}"

    message = f"{ts}.".encode("utf-8") + body_bytes
    digest = hmac.new(secret.encode("utf-8"), message, getattr(hashlib, algo)).hexdigest()

    if not hmac.compare_digest(sig_recv, digest):
        return False, None, "signature mismatch"

    event_type = headers.get(DEFAULT_HEADER_EVT)
    return True, event_type, None
