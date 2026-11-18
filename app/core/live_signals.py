# app/core/live_signals.py
"""
Segnali silenziosi durante il live (Fase 2, punto 6 — 2026-11-18).

L'ospite tocca "Non sento", "Più piano", "Ho una domanda" o "👍"; la guida
vede quante persone l'hanno chiesto di recente, dentro lo stato della
sessione che già legge ogni pochi secondi.

Sono informazioni di pochi minuti: si tengono in memoria (il backend gira in
un solo processo), senza database. Ogni ospite conta una volta per tipo; il
segnale scade da solo dopo una finestra di tempo, oppure quando la guida lo
"ha visto" e lo azzera.
"""
from __future__ import annotations

import threading
import time

KINDS = ("cant_hear", "slower", "question", "like")

# Per quanto resta visibile un segnale (secondi).
WINDOW = {"cant_hear": 60, "slower": 60, "question": 120, "like": 20}

# Un ospite non può ripetere lo stesso segnale più spesso di così.
COOLDOWN = 5

_lock = threading.Lock()
# session_id -> kind -> listener_id -> timestamp
_store: dict[str, dict[str, dict[str, float]]] = {}
# session_id -> kind -> quanti segnali in tutto (per il riepilogo di fine tour)
_totals: dict[str, dict[str, int]] = {}


def _prune(session: dict[str, dict[str, float]], now: float) -> None:
    for kind, by_listener in session.items():
        limit = now - WINDOW[kind]
        for lid in [l for l, ts in by_listener.items() if ts < limit]:
            del by_listener[lid]


def add(session_id: str, listener_id: str, kind: str) -> bool:
    """Registra un segnale. False se arriva troppo presto dopo il precedente."""
    if kind not in KINDS:
        raise ValueError(kind)
    now = time.time()
    with _lock:
        session = _store.setdefault(session_id, {k: {} for k in KINDS})
        last = session[kind].get(listener_id)
        if last is not None and now - last < COOLDOWN:
            return False
        session[kind][listener_id] = now
        tot = _totals.setdefault(session_id, {k: 0 for k in KINDS})
        tot[kind] += 1
        return True


def counts(session_id: str) -> dict[str, int]:
    now = time.time()
    with _lock:
        session = _store.get(session_id)
        if not session:
            return {k: 0 for k in KINDS}
        _prune(session, now)
        return {k: len(session[k]) for k in KINDS}


def totals(session_id: str) -> dict[str, int]:
    with _lock:
        return dict(_totals.get(session_id) or {k: 0 for k in KINDS})


def clear(session_id: str, kind: str | None = None) -> None:
    with _lock:
        session = _store.get(session_id)
        if not session:
            return
        for k in [kind] if kind in KINDS else KINDS:
            session[k].clear()


def forget(session_id: str) -> None:
    """A fine sessione."""
    with _lock:
        _store.pop(session_id, None)
        _totals.pop(session_id, None)
