# test_hmac_webhook.py
import hmac
import hashlib
import time
import json
import requests

# === MODALITÀ: "local" oppure "prod" ===
MODE = "prod"  # cambia in "local" se vuoi testare il server in localhost

if MODE == "local":
    # Server locale
    URL = "http://127.0.0.1:8000/api/events/receive-hmac"
    # Secret di sviluppo (deve combaciare con WEBHOOK_HMAC_SECRET nel .env locale)
    SECRET = "prova123"
else:
    # Server di PRODUZIONE su Railway
    URL = "https://voiceguide-airlink-backend-production.up.railway.app/api/events/receive-hmac"
    # Secret di produzione (deve combaciare con WEBHOOK_HMAC_SECRET su Railway)
    SECRET = "prova123"


def build_sig(ts: int, raw: bytes) -> str:
    """
    Costruisce la firma HMAC SHA256 nel formato:
    HMAC(secret, "<timestamp>.<payload_json>")
    """
    return hmac.new(SECRET.encode(), f"{ts}.".encode() + raw, hashlib.sha256).hexdigest()


def send(payload: dict) -> None:
    raw = json.dumps(payload, separators=(",", ":")).encode()
    ts = int(time.time())
    sig = build_sig(ts, raw)

    print("\n=== SENDING PAYLOAD ===")
    print("MODE     :", MODE)
    print("URL      :", URL)
    print("TIMESTAMP:", ts)
    print("PAYLOAD  :", payload)
    print("SIGNATURE:", sig)

    # Header combinato (nostro default)
    headers_combined = {
        "X-Webhook-Signature": f"t={ts},v1={sig}",
        "Content-Type": "application/json",
    }
    r1 = requests.post(URL, data=raw, headers=headers_combined)
    print("COMBINED → HTTP", r1.status_code, "| body:", r1.text)

    # Header doppi (compatibilità con altri receiver)
    headers_dual = {
        "X-Webhook-Timestamp": str(ts),
        "X-Webhook-Signature": f"v1={sig}",  # oppure solo hex: sig
        "Content-Type": "application/json",
    }
    r2 = requests.post(URL, data=raw, headers=headers_dual)
    print("DUAL     → HTTP", r2.status_code, "| body:", r2.text)


if __name__ == "__main__":
    print("=== TEST HMAC WEBHOOK VoiceGuide AirLink ===")
    print("MODE:", MODE)
    print("---------------------------------------------")

    send({"type": "session_started", "session_id": "11111111-1111-1111-1111-111111111111"})
    send(
        {
            "type": "listener_joined",
            "session_id": "11111111-1111-1111-1111-111111111111",
            "listener_id": "L-001",
        }
    )
    send({"type": "session_ended", "session_id": "11111111-1111-1111-1111-111111111111"})
