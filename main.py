# app/main.py
from __future__ import annotations

import os
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

# ------------------------------------------------------------
# IMPORT ROUTER PRINCIPALI E ADDON
# ------------------------------------------------------------
# Core API centralizzata (licenze, sessioni, join, ecc.)
from app.api.routes import router as api_router

# Addon API (stats)
from app.api import stats

# Router Admin unificato (/api/admin/overview, /api/admin/licenses, azioni)
from app.api import admin as admin_api

# Routers aggiuntivi (Export CSV, Webhook Test, Admin Notify)
from app.routers.events_export import router as events_export_router
from app.routers.webhook_test import router as webhook_test_router
from app.routers.admin_notify import router as admin_notify_router

# Routers amministrativi avanzati
from app.routers.admin_live import router as admin_live_router
from app.routers.admin_events import router as admin_events_router

# DB session
from app.db.session import get_db

# Scheduler automatico di retry eventi
from app.core.scheduler import start_scheduler, stop_scheduler


# ------------------------------------------------------------
# CREAZIONE DELL'APPLICAZIONE FASTAPI
# ------------------------------------------------------------
def create_app() -> FastAPI:
    """Crea e configura l'applicazione FastAPI VoiceGuide AirLink."""
    app_version = os.getenv("APP_VERSION", "dev")

    app = FastAPI(
        title="VoiceGuide AirLink API",
        version=app_version,
        description=(
            "Backend ufficiale per VoiceGuide.it AirLink — "
            "gestione licenze, sessioni live e connessioni guidate tra "
            "guide e ascoltatori tramite PIN, con Event Bus, retry automatico "
            "e monitoraggio amministrativo."
        ),
        contact={
            "name": "VoiceGuide.it",
            "url": "https://www.voiceguide.it",
            "email": "stefano.licopoli@gmail.com",
        },
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # --------------------------------------------------------
    # CORS
    # --------------------------------------------------------
    ALLOWED_ORIGINS = [
        "https://voiceguide.it",
        "https://www.voiceguide.it",
        "http://localhost",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://127.0.0.1",
    ]

    extra = os.getenv("VOICEGUIDE_CORS_EXTRA")
    if extra:
        for item in [x.strip() for x in extra.split(",") if x.strip()]:
            if item not in ALLOWED_ORIGINS:
                ALLOWED_ORIGINS.append(item)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --------------------------------------------------------
    # ROUTES PRINCIPALI
    # --------------------------------------------------------
    app.include_router(api_router, prefix="")

    # --------------------------------------------------------
    # ROUTES ADDON
    # --------------------------------------------------------
    app.include_router(stats.router)
    app.include_router(events_export_router)
    app.include_router(admin_notify_router)
    app.include_router(webhook_test_router)

    # --------------------------------------------------------
    # ROUTES ADMIN
    # --------------------------------------------------------
    app.include_router(admin_live_router)
    app.include_router(admin_events_router)
    app.include_router(admin_api.router)

    # --------------------------------------------------------
    # ROOT DI SERVIZIO
    # --------------------------------------------------------
    @app.get("/", tags=["root"])
    def root():
        return {
            "status": "online",
            "service": "VoiceGuide AirLink API",
            "version": app_version,
            "message": "AVE SEMPER! ⚔️ La connessione è attiva.",
        }

    # --------------------------------------------------------
    # VERSION
    # --------------------------------------------------------
    @app.get("/api/version", tags=["system"])
    def version():
        """Versione dell'applicazione (gestita via env APP_VERSION)."""
        return {"version": app_version}

    # --------------------------------------------------------
    # 🩺 HEALTHZ ENDPOINT (API + DB PING)
    # --------------------------------------------------------
    @app.get("/api/healthz", tags=["system"])
    def healthz(db: Session = Depends(get_db)):
        """
        Endpoint di verifica automatica per Railway e monitoring.
        Controlla sia l'API sia la reachability del DB.
        """
        try:
            db.execute(text("SELECT 1"))
            return {
                "status": "ok",
                "service": "voiceguide-airlink-backend",
                "db": "ok",
                "version": app_version,
            }
        except Exception as e:
            # 503 = Service Unavailable
            raise HTTPException(
                status_code=503,
                detail={
                    "status": "degraded",
                    "db": "error",
                    "error": str(e),
                    "version": app_version,
                },
            )

    # --------------------------------------------------------
    # EVENTI DI AVVIO / ARRESTO
    # --------------------------------------------------------
    @app.on_event("startup")
    async def _on_startup():
        start_scheduler(app)

    @app.on_event("shutdown")
    async def _on_shutdown():
        await stop_scheduler(app)

    return app


# ------------------------------------------------------------
# ISTANZA APPLICAZIONE
# ------------------------------------------------------------
app = create_app()

# ------------------------------------------------------------
# AVVIO LOCALE
# ------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
