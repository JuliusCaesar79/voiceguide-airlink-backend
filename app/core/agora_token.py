# app/core/agora_token.py
from __future__ import annotations

import os
import time
from typing import Optional

from agora_token_builder import RtcTokenBuilder

# Ruoli Agora: guida = publisher (trasmette), ospite = subscriber (solo ascolto)
ROLE_PUBLISHER = 1
ROLE_SUBSCRIBER = 2

DEFAULT_EXPIRE_SECONDS = 4 * 60 * 60  # 4h, coerente col fallback duration_minutes delle licenze


def generate_rtc_token(
    *,
    channel_name: str,
    uid: int = 0,
    role: int = ROLE_SUBSCRIBER,
    expire_seconds: int = DEFAULT_EXPIRE_SECONDS,
) -> Optional[str]:
    """
    Genera un token Agora RTC per channel/uid/ruolo indicati.

    Ritorna None se AGORA_APP_ID o AGORA_APP_CERTIFICATE non sono impostati
    nell'ambiente: finché l'App Certificate non viene attivato lato Agora
    Console, l'app continua a funzionare in modalità solo-AppId (token None)
    esattamente come oggi, senza rotture.
    """
    app_id = os.getenv("AGORA_APP_ID")
    app_certificate = os.getenv("AGORA_APP_CERTIFICATE")

    if not app_id or not app_certificate or not channel_name:
        return None

    privilege_expired_ts = int(time.time()) + max(60, int(expire_seconds))

    return RtcTokenBuilder.buildTokenWithUid(
        app_id, app_certificate, channel_name, uid, role, privilege_expired_ts
    )
