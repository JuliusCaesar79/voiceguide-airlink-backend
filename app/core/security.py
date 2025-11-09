# app/core/security.py
# ⚠️ DEV-ONLY: decoder JWT senza verifica firma (basta per Swagger/test)
# In produzione sostituiscilo con una verifica firmata (es. PyJWT o python-jose).

from fastapi.security import OAuth2PasswordBearer
from fastapi import HTTPException, status
import base64, json
from typing import Dict, Any

# Usa il tuo endpoint reale di login se differente
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

def _b64url_decode(segment: str) -> bytes:
    padding = '=' * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + padding)

def decode_token(token: str) -> Dict[str, Any]:
    """
    Decodifica SOLO il payload del JWT senza verificare la firma.
    Ritorna un dict con le claim (es. {"sub": "...", "role": "admin"}).
    """
    try:
        parts = token.split(".")
        if len(parts) != 3:
            raise ValueError("Invalid JWT format")
        payload_segment = parts[1]
        payload_bytes = _b64url_decode(payload_segment)
        payload = json.loads(payload_bytes.decode("utf-8"))
        return payload
    except Exception:
        # Token non valido/illeggibile
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )
