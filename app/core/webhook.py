from __future__ import annotations

import asyncio
import hmac
import hashlib
import json
import time
from typing import Dict, Any, Tuple, Optional

import httpx

# Preferiamo l'istanza "settings" come nel resto del codice
# ma restiamo compatibili se il progetto usa ancora get_settings()
try:
    from app.core.config import settings  # type: ignore
except Exception:  # pragma: no cover - fallback legacy
    from app.core.config import get_settings  # type: ignore
    settings = get_settings()  # type: ignore


# ------------------------------------------------------------
# Helpers firma HMAC (compatibili e configurabili)
# ------------------------------------------------------------
def _pick_hmac_secret() -> Optional[str]:
    """
    Prova i nuovi nomi env (WEBHOOK_HMAC_SECRET) e poi i legacy (ADMIN_WEBHOOK_SECRET).
    Ritorna None se non configurato.
    """
    secret = getattr(settings, "WEBHOOK_HMAC_SECRET", None) or getattr(settings, "ADMIN_WEBHOOK_SECRET", None)
    if secret:
        secret = str(secret).strip()
    return secret or None


def _pick_hmac_header_name() -> str:
    """
    Usa il nuovo header (WEBHOOK_HMAC_HEADER) se presente, altrimenti quello legacy.
    """
    return (
        getattr(settings, "WEBHOOK_HMAC_HEADER", None)
        or "X-Webhook-Signature"  # legacy default
    )


def _pick_hmac_algo() -> str:
    """
    Algoritmo di firma. Default sha256.
    """
    return getattr(settings, "WEBHOOK_HMAC_ALGO", None) or "sha256"


def _hmac_digest(secret: str, message: bytes, algo: str = "sha256") -> str:
    """
    Calcola HMAC esadecimale con algoritmo scelto (sha256/sha512...).
    """
    algo = algo.lower()
    if not hasattr(hashlib, algo):
        raise ValueError(f"Unsupported HMAC algo: {algo}")
    return hmac.new(secret.encode("utf-8"), message, getattr(hashlib, algo)).hexdigest()


# ------------------------------------------------------------
# Webhook POST con retry + firma HMAC e timestamp anti-replay
# ------------------------------------------------------------
async def post_webhook(event_type: str, payload: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """
    Invia un webhook amministrativo con:
      - Body JSON: {"event_type": <str>, "payload": <dict>}
      - Header Content-Type
      - Header firma HMAC opzionale (nome header configurabile)
      - Header timestamp anti-replay: X-Webhook-Timestamp
      - Header tipo evento: X-Webhook-Event

    Ritorna (ok, error) dove error è None se ok=True.
    """
    admin_url = (getattr(settings, "ADMIN_WEBHOOK_URL", None) or "").strip()
    if not admin_url:
        return False, "ADMIN_WEBHOOK_URL not configured"

    # Body (retro-compatibile con la tua implementazione esistente)
    body_dict = {"event_type": event_type, "payload": payload}
    body_bytes = json.dumps(body_dict, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    # Header base
    headers: Dict[str, str] = {
        "Content-Type": "application/json",
        "X-Webhook-Event": event_type,
    }

    # Timestamp anti-replay
    ts = str(int(time.time()))
    headers["X-Webhook-Timestamp"] = ts

    # Firma HMAC (se disponibile un secret)
    secret = _pick_hmac_secret()
    if secret:
        header_name = _pick_hmac_header_name()
        algo = _pick_hmac_algo()
        # Firma di "<timestamp>.<body>"
        signed_message = f"{ts}.".encode("utf-8") + body_bytes
        headers[header_name] = _hmac_digest(secret, signed_message, algo=algo)

    # Timeout e retry (compatibile con env esistenti)
    timeout_seconds = float(getattr(settings, "ADMIN_WEBHOOK_TIMEOUT_SECONDS", 5))
    max_retries = int(max(1, getattr(settings, "ADMIN_WEBHOOK_MAX_RETRIES", 3)))

    timeout = httpx.Timeout(timeout_seconds)
    backoff = 0.5

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        for attempt in range(1, max_retries + 1):
            try:
                resp = await client.post(admin_url, content=body_bytes, headers=headers)
                if 200 <= resp.status_code < 300:
                    return True, None
                err = f"HTTP {resp.status_code}: {resp.text[:500]}"
            except Exception as e:
                err = str(e)

            if attempt < max_retries:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 8.0)  # exponential backoff (cap 8s)
            else:
                return False, err
