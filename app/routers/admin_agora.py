import os
import requests
from fastapi import APIRouter, HTTPException
from requests.auth import HTTPBasicAuth

router = APIRouter(prefix="/admin/agora", tags=["Admin Agora"])

@router.get("/test-auth")
def test_auth():
    app_id = os.getenv("AGORA_APP_ID")
    customer_id = os.getenv("AGORA_CUSTOMER_ID")
    customer_secret = os.getenv("AGORA_CUSTOMER_SECRET")

    if not app_id or not customer_id or not customer_secret:
        raise HTTPException(status_code=500, detail="Missing Agora env vars")

    url = "https://api.agora.io/dev/v1/kicking-rule"

    payload = {
        "appid": app_id,
        "cname": "THZ1S9",
        "uid": "0",
        "time": 60,
        "privileges": ["join_channel"],
    }

    r = requests.post(
        url,
        json=payload,
        auth=HTTPBasicAuth(customer_id, customer_secret),
        headers={"Content-Type": "application/json"},
        timeout=15,
    )

    return {"status_code": r.status_code, "body": r.text}