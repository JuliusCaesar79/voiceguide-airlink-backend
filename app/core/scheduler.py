# app/core/scheduler.py
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from fastapi import FastAPI
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal  # Factory SQLAlchemy
from app.services.event_bus import retry_failed_events

# 🆕 Logica auto-close sessioni
from app.core.session_end import close_all_expired_sessions
from app.core.utils import log_event

# 🆕 Kill Switch Agora (internal)
from app.routers.admin_agora import disband_channel_internal

# Usiamo il logger di uvicorn così i messaggi compaiono in console
logger = logging.getLogger("uvicorn.error")


def _kill_switch_disband(*, db: Session, session, reason: str):
    """
    Kill switch best-effort per auto-close:
    NO Alembic -> cname = session.pin
    """
    cname = getattr(session, "pin", None)
    if not isinstance(cname, str) or not cname.strip():
        try:
            log_event(db, "KILL_SWITCH_FAIL", "missing_pin_cname", session_id=str(session.id))
        except Exception:
            pass
        logger.warning("[auto-close] KILL_SWITCH_FAIL session_id=%s missing_pin_cname", session.id)
        return {"ok": False, "error": "missing_pin"}

    try:
        log_event(db, "KILL_SWITCH_START", f"reason={reason}", session_id=str(session.id))
    except Exception:
        pass

    result = disband_channel_internal(cname=cname.strip(), time=60, privileges=["join_channel"])
    return {"ok": True, "cname": cname.strip(), "result": result}


# ---------------------------------------------------------------------
# LOOP 1: RETRY EVENTI FALLITI
# ---------------------------------------------------------------------
async def _retry_loop(app: FastAPI) -> None:
    interval = max(5, int(getattr(settings, "RETRY_INTERVAL_SECONDS", 60)))
    limit = max(1, int(getattr(settings, "RETRY_LIMIT", 200)))

    while True:
        try:
            db: Session = SessionLocal()
            try:
                class _ShimBT:
                    def add_task(self, coro, *args, **kwargs):
                        asyncio.create_task(coro(*args, **kwargs))

                scheduled = retry_failed_events(db, _ShimBT(), limit=limit)
                if scheduled:
                    msg = f"[scheduler] retried {len(scheduled)} failed events"
                    print(msg)
                    logger.info(msg)
            finally:
                db.close()
        except Exception as e:
            msg = f"[scheduler] error in retry loop: {e!r}"
            print(msg)
            logger.exception(msg)

        await asyncio.sleep(interval)


# ---------------------------------------------------------------------
# LOOP 2: AUTO-CHIUSURA SESSIONI SCADUTE
# ---------------------------------------------------------------------
async def _auto_close_loop(app: FastAPI) -> None:
    interval = max(15, int(getattr(settings, "AUTO_CLOSE_INTERVAL_SECONDS", 60)))

    start_msg = (
        f"[auto-close] loop started (interval={interval}s): "
        "controllo sessioni scadute abilitato."
    )
    print(start_msg)
    logger.info(start_msg)

    while True:
        try:
            db: Session = SessionLocal()
            try:
                closed = close_all_expired_sessions(
                    db,
                    event_logger=log_event,
                    kill_switch=_kill_switch_disband,   # ✅ QUI: Agora disband automatico
                )
                if closed:
                    msg = f"[auto-close] chiuse automaticamente {closed} sessioni scadute in questo tick."
                    print(msg)
                    logger.info(msg)
            finally:
                db.close()
        except Exception as e:
            msg = f"[auto-close] errore nel loop auto-close: {e!r}"
            print(msg)
            logger.exception(msg)

        await asyncio.sleep(interval)


# ---------------------------------------------------------------------
# AVVIO / ARRESTO SCHEDULER
# ---------------------------------------------------------------------
def start_scheduler(app: FastAPI) -> None:
    if not getattr(settings, "SCHEDULER_ENABLED", True):
        print("[scheduler] disabled by settings")
        app.state.retry_task = None
        app.state.auto_close_task = None
        return

    loop = asyncio.get_event_loop()

    if getattr(app.state, "retry_task", None) is None:
        app.state.retry_task = loop.create_task(_retry_loop(app))
        print("[scheduler] started (retry loop)")
        logger.info("[scheduler] started (retry loop)")

    if getattr(app.state, "auto_close_task", None) is None:
        app.state.auto_close_task = loop.create_task(_auto_close_loop(app))
        print("[auto-close] scheduler started (auto-close loop)")
        logger.info("[auto-close] scheduler started (auto-close loop)")


async def stop_scheduler(app: FastAPI) -> None:
    retry_task: Optional[asyncio.Task] = getattr(app.state, "retry_task", None)
    if retry_task is not None:
        retry_task.cancel()
        try:
            await retry_task
        except asyncio.CancelledError:
            pass
        app.state.retry_task = None
        print("[scheduler] stopped (retry loop)")
        logger.info("[scheduler] stopped (retry loop)")

    auto_task: Optional[asyncio.Task] = getattr(app.state, "auto_close_task", None)
    if auto_task is not None:
        auto_task.cancel()
        try:
            await auto_task
        except asyncio.CancelledError:
            pass
        app.state.auto_close_task = None
        print("[auto-close] scheduler stopped (auto-close loop)")
        logger.info("[auto-close] scheduler stopped (auto-close loop)")