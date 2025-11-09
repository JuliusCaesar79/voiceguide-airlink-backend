# app/core/scheduler.py
from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import FastAPI
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal  # Assunto: esiste come factory SQLAlchemy
from app.services.event_bus import retry_failed_events


async def _retry_loop(app: FastAPI) -> None:
    """
    Loop periodico:
    - ogni RETRY_INTERVAL_SECONDS seleziona gli eventi FAILED e li riprogramma.
    - usa un limite 'RETRY_LIMIT' per batch.
    - non lancia eccezioni verso l'alto (il loop non deve morire).
    """
    interval = max(5, int(getattr(settings, "RETRY_INTERVAL_SECONDS", 60)))
    limit = max(1, int(getattr(settings, "RETRY_LIMIT", 200)))

    while True:
        try:
            # Usa una sessione DB effimera per ogni giro
            db: Session = SessionLocal()
            try:
                # Non abbiamo BackgroundTasks in un job; scheduliamo consegna direttamente
                # riusando retry_failed_events che accoda _deliver_event come task asyncio
                # tramite BackgroundTasks emulato? -> qui facciamo una semplice shim.
                class _ShimBT:
                    def add_task(self, coro, *args, **kwargs):
                        # Avvia l'async task senza attendere
                        asyncio.create_task(coro(*args, **kwargs))

                scheduled = retry_failed_events(db, _ShimBT(), limit=limit)
                if scheduled:
                    # Facoltativo: loggare in console
                    print(f"[scheduler] retried {len(scheduled)} failed events")
            finally:
                db.close()
        except Exception as e:
            # Non deve mai spezzare il loop
            print(f"[scheduler] error: {e!r}")

        await asyncio.sleep(interval)


def start_scheduler(app: FastAPI) -> None:
    """
    Avvia il task asincrono solo se abilitato via settings.
    Salva l'handle in app.state.retry_task.
    """
    if not getattr(settings, "SCHEDULER_ENABLED", True):
        print("[scheduler] disabled by settings")
        app.state.retry_task = None
        return

    # Evita doppi avvii in reload
    if getattr(app.state, "retry_task", None) is not None:
        return

    app.state.retry_task = asyncio.create_task(_retry_loop(app))
    print("[scheduler] started")


async def stop_scheduler(app: FastAPI) -> None:
    """
    Arresta il task in modo pulito su shutdown.
    """
    task: Optional[asyncio.Task] = getattr(app.state, "retry_task", None)
    if task is not None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        app.state.retry_task = None
        print("[scheduler] stopped")
