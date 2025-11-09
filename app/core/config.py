# app/core/config.py
from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional

from pydantic import BaseModel, AnyUrl

# Carica variabili da .env (se presente)
from dotenv import load_dotenv
load_dotenv()


class Settings(BaseModel):
    # --- App base ---
    APP_NAME: str = os.getenv("APP_NAME", "VoiceGuide AirLink API")
    APP_DEBUG: bool = os.getenv("APP_DEBUG", "true").lower() == "true"

    # --- Database ---
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://postgres:postgres@localhost:5432/voiceguide_airlink_dev",
    )

    # --- Redis (se previsto per future queue/cache) ---
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    # --- Sicurezza / JWT ---
    SECRET_KEY: str = os.getenv("SECRET_KEY", "changeme")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "120"))

    # --- 🔔 Webhook Amministrativo (Event Bus) ---
    ADMIN_WEBHOOK_URL: Optional[str] = os.getenv("ADMIN_WEBHOOK_URL") or None
    ADMIN_WEBHOOK_SECRET: Optional[str] = os.getenv("ADMIN_WEBHOOK_SECRET") or None
    ADMIN_WEBHOOK_TIMEOUT_SECONDS: int = int(os.getenv("ADMIN_WEBHOOK_TIMEOUT_SECONDS", "5"))
    ADMIN_WEBHOOK_MAX_RETRIES: int = int(os.getenv("ADMIN_WEBHOOK_MAX_RETRIES", "5"))

    # --- ⚙️ Scheduler (retry automatico Event Bus) ---
    SCHEDULER_ENABLED: bool = os.getenv("SCHEDULER_ENABLED", "true").lower() == "true"
    RETRY_INTERVAL_SECONDS: int = int(os.getenv("RETRY_INTERVAL_SECONDS", "60"))
    RETRY_LIMIT: int = int(os.getenv("RETRY_LIMIT", "200"))

    # --- Logging ---
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # --- Environment flags ---
    ENV: str = os.getenv("ENV", "dev")
    DEBUG: bool = APP_DEBUG


@lru_cache
def get_settings() -> Settings:
    """Restituisce una singola istanza cache di Settings."""
    return Settings()


# ✅ Istanza globale per import diretto: from app.core.config import settings
settings = get_settings()
