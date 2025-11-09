from __future__ import annotations
import json, logging

log = logging.getLogger("webhook")

def post_json(payload: dict):
    log.info("[WEBHOOK] %s", json.dumps(payload, default=str))
    # in futuro: invio HTTP a Zapier/Make o URL configurabile
    return {"ok": True, "echo": payload}
