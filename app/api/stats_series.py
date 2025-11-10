from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as OrmSession
from datetime import datetime, timedelta, timezone
from typing import List, Dict
from zoneinfo import ZoneInfo

# DB session getter
from app.db.session import get_db

# ORM model
from app.models.session import Session as SessionModel


router = APIRouter(prefix="/api/stats", tags=["stats"])


class DayPoint(BaseModel):
    t: str = Field(..., description="Giorno in formato YYYY-MM-DD (timezone richiesto)")
    sessions_total: int = 0
    avg_minutes: float = 0.0
    active_peak: int = 0


class SeriesResponse(BaseModel):
    range: Dict[str, str]
    tz: str
    days: int
    series: List[DayPoint]
    note: str | None = None


@router.get("/series", response_model=SeriesResponse)
def stats_series(
    days: int = Query(7, ge=1, le=60, description="Numero di giorni da restituire (incluso oggi)"),
    tz: str = Query("Europe/Rome", description="Timezone IANA per il raggruppamento per giorno"),
    db: OrmSession = Depends(get_db),
):
    """
    Serie temporale KPI per giorno.

    Definizioni:
    - sessions_total: numero di sessioni *iniziate* quel giorno (conteggio per started_at nel giorno).
    - avg_minutes: durata media (in minuti) delle sessioni *iniziate* quel giorno.
      Per le sessioni ancora attive, la durata è calcolata fino a "now" (timezone fornita).
    - active_peak: picco di concorrenza (numero massimo di sessioni sovrapposte) durante quel giorno,
      calcolato considerando l'intervallo [giorno 00:00, giorno 23:59:59.999] nella timezone richiesta.

    Safe-mode:
    - Se la tabella/colonne non sono disponibili o si verifica un errore, ritorna serie con zero e nota esplicativa.
    """
    try:
        tzinfo = ZoneInfo(tz)
    except Exception:
        tzinfo = ZoneInfo("UTC")
        tz = "UTC"

    now_tz = datetime.now(tzinfo)
    # inizio di oggi (nella tz richiesta)
    today_start_tz = now_tz.replace(hour=0, minute=0, second=0, microsecond=0)
    # finestra: da (oggi - (days-1)) 00:00 fino a (oggi + 1) 00:00 escluso
    window_start_tz = today_start_tz - timedelta(days=days - 1)
    window_end_tz = today_start_tz + timedelta(days=1)

    # Conversione in UTC per il filtro DB
    window_start_utc = window_start_tz.astimezone(timezone.utc)
    window_end_utc = window_end_tz.astimezone(timezone.utc)
    now_utc = now_tz.astimezone(timezone.utc)

    # Prepara contenitori per tutti i giorni
    day_keys = [
        (window_start_tz + timedelta(days=i)).date().isoformat()
        for i in range(days)
    ]

    # Serie inizializzata
    series_map: Dict[str, Dict[str, float | int | list]] = {}
    for d in day_keys:
        series_map[d] = {
            "sessions_total": 0,
            "dur_sum_minutes": 0.0,  # per calcolo media
            "dur_count": 0,
            # Eventi per calcolo peak concurrency (lista di timestamp secondi nel giorno)
            "events": [],  # elementi: (seconds_from_midnight, +1/-1)
        }

    try:
        # Query sessioni che toccano la finestra (anche iniziate prima ma ancora attive durante la finestra)
        # Condizione: started_at < window_end AND (ended_at IS NULL OR ended_at >= window_start)
        q = (
            db.query(SessionModel)
            .filter(SessionModel.started_at < window_end_utc)
            .filter(
                (SessionModel.ended_at == None)  # noqa: E711
                | (SessionModel.ended_at >= window_start_utc)
            )
        )

        sessions = q.all()

        # Elaborazione
        for s in sessions:
            # Normalizza intervallo sessione nella tz richiesta
            s_start_utc = s.started_at
            # ended_at può essere None → usa now_utc
            s_end_utc = s.ended_at or now_utc

            # clamp alla finestra (UTC)
            start_utc = max(s_start_utc, window_start_utc)
            end_utc = min(s_end_utc, window_end_utc)
            if end_utc <= start_utc:
                continue

            start_tz = start_utc.astimezone(tzinfo)
            end_tz = end_utc.astimezone(tzinfo)

            # ——— SESSIONS_TOTAL & AVG_MINUTES (bucket sul giorno di start effettivo) ———
            start_bucket_date = start_tz.date().isoformat()
            if start_bucket_date in series_map:
                # Conteggio sessioni iniziate quel giorno
                series_map[start_bucket_date]["sessions_total"] += 1

                # Durata (se la sessione finisce prima di window_end_tz o è ancora attiva, calcola sull'intervallo clampato)
                dur_minutes = (end_tz - start_tz).total_seconds() / 60.0
                if dur_minutes < 0:
                    dur_minutes = 0.0
                series_map[start_bucket_date]["dur_sum_minutes"] += dur_minutes
                series_map[start_bucket_date]["dur_count"] += 1

            # ——— ACTIVE_PEAK (peak concurrency per ciascun giorno attraversato) ———
            # Spezza la sessione per ogni giorno che tocca nella finestra
            day_cursor = start_tz.replace(hour=0, minute=0, second=0, microsecond=0)
            while day_cursor < end_tz:
                day_end = day_cursor + timedelta(days=1)
                # intervallo effettivo in questo giorno
                seg_start = max(start_tz, day_cursor)
                seg_end = min(end_tz, day_end)
                if seg_end > seg_start:
                    day_key = day_cursor.date().isoformat()
                    if day_key in series_map:
                        # secondi dal mezzanotte del day_key
                        s1 = (seg_start - day_cursor).total_seconds()
                        s2 = (seg_end - day_cursor).total_seconds()
                        # Inseriamo +1 all'inizio e -1 alla fine per sweep line
                        series_map[day_key]["events"].append((s1, +1))
                        series_map[day_key]["events"].append((s2, -1))
                day_cursor = day_end

        # Calcolo finale dei peak e media
        out_series: List[DayPoint] = []
        for d in day_keys:
            rec = series_map[d]
            # peak concurrency
            events = rec["events"]
            events.sort(key=lambda x: (x[0], -x[1]))  # +1 prima di -1 a parità di tempo
            cur = 0
            peak = 0
            for _, delta in events:
                cur += delta
                if cur > peak:
                    peak = cur

            # avg minutes
            avg = 0.0
            if rec["dur_count"] > 0:
                avg = rec["dur_sum_minutes"] / rec["dur_count"]

            out_series.append(
                DayPoint(
                    t=d,
                    sessions_total=int(rec["sessions_total"]),
                    avg_minutes=round(float(avg), 2),
                    active_peak=int(peak),
                )
            )

        return SeriesResponse(
            range={
                "from": window_start_tz.isoformat(),
                "to": (window_end_tz - timedelta(microseconds=1)).isoformat(),
            },
            tz=tz,
            days=days,
            series=out_series,
            note=None,
        )
    except Exception as e:
        # Safe-mode: ritorna struttura vuota con spiegazione
        out_series = [
            DayPoint(t=d, sessions_total=0, avg_minutes=0.0, active_peak=0) for d in day_keys
        ]
        return SeriesResponse(
            range={
                "from": window_start_tz.isoformat(),
                "to": (window_end_tz - timedelta(microseconds=1)).isoformat(),
            },
            tz=tz,
            days=days,
            series=out_series,
            note=f"safe-mode: {type(e).__name__}",
        )
