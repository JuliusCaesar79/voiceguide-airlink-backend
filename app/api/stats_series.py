from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as OrmSession
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Tuple
from zoneinfo import ZoneInfo

# DB session getter
from app.db.session import get_db

# ORM model
from app.models.session import Session as SessionModel


router = APIRouter(prefix="/api/stats", tags=["stats"])


class DayPoint(BaseModel):
    t: str = Field(..., description="Giorno in formato YYYY-MM-DD (timezone richiesta)")
    sessions_total: int = 0
    avg_minutes: float = 0.0
    active_peak: int = 0


class SeriesResponse(BaseModel):
    range: Dict[str, str]
    tz: str
    days: int
    series: List[DayPoint]
    note: str | None = None


def _utc(dt: datetime | None) -> datetime | None:
    """Rende il datetime timezone-aware UTC.
    - None -> None
    - naive -> assume UTC (replace tzinfo=UTC)
    - aware -> convert to UTC
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@router.get("/series", response_model=SeriesResponse)
def stats_series(
    days: int = Query(7, ge=1, le=60, description="Numero di giorni (incluso oggi)"),
    tz: str = Query("Europe/Rome", description="Timezone IANA per il raggruppamento per giorno"),
    db: OrmSession = Depends(get_db),
):
    """
    Serie temporale KPI per giorno.

    Definizioni:
    - sessions_total: numero di sessioni *iniziate* quel giorno (bucket su started_at nella TZ richiesta).
    - avg_minutes: durata media (minuti) delle sessioni iniziate quel giorno.
      Le sessioni ancora attive usano 'now'.
    - active_peak: picco di concorrenza nello stesso giorno (sweep line sugli intervalli sovrapposti).

    Safe-mode: in caso di errore, ritorna serie a zero con 'note' esplicativa.
    """
    try:
        tzinfo = ZoneInfo(tz)
    except Exception:
        tzinfo = ZoneInfo("UTC")
        tz = "UTC"

    try:
        now_tz = datetime.now(tzinfo)
        today_start_tz = now_tz.replace(hour=0, minute=0, second=0, microsecond=0)

        window_start_tz = today_start_tz - timedelta(days=days - 1)
        window_end_tz = today_start_tz + timedelta(days=1)

        # Conversione in UTC per i filtri DB
        window_start_utc = window_start_tz.astimezone(timezone.utc)
        window_end_utc = window_end_tz.astimezone(timezone.utc)
        now_utc = now_tz.astimezone(timezone.utc)

        # Prepara chiavi giorni
        day_keys = [
            (window_start_tz + timedelta(days=i)).date().isoformat()
            for i in range(days)
        ]

        # Inizializza serie
        series_map: Dict[str, Dict[str, float | int | list]] = {
            d: {
                "sessions_total": 0,
                "dur_sum_minutes": 0.0,
                "dur_count": 0,
                "events": [],  # (seconds_from_midnight, +1/-1)
            }
            for d in day_keys
        }

        # Prendi le sessioni che toccano la finestra
        q = (
            db.query(SessionModel)
            .filter(SessionModel.started_at < window_end_utc)
            .filter(
                (SessionModel.ended_at == None)  # noqa: E711
                | (SessionModel.ended_at >= window_start_utc)
            )
        )
        sessions: List[SessionModel] = q.all()

        for s in sessions:
            # Normalizza a UTC (gestisce naive/aware)
            s_start_utc = _utc(s.started_at)
            s_end_utc = _utc(s.ended_at) or now_utc

            if s_start_utc is None:
                # riga malformata: salta
                continue

            # clamp alla finestra
            start_utc = max(s_start_utc, window_start_utc)
            end_utc = min(s_end_utc, window_end_utc)
            if end_utc <= start_utc:
                continue

            # Proiezione nella TZ richiesta
            start_tz = start_utc.astimezone(tzinfo)
            end_tz = end_utc.astimezone(tzinfo)

            # ---- bucket di start (sessions_total & avg_minutes)
            start_bucket_date = start_tz.date().isoformat()
            if start_bucket_date in series_map:
                series_map[start_bucket_date]["sessions_total"] += 1
                dur_minutes = max(0.0, (end_tz - start_tz).total_seconds() / 60.0)
                series_map[start_bucket_date]["dur_sum_minutes"] += dur_minutes
                series_map[start_bucket_date]["dur_count"] += 1

            # ---- peak concurrency (sweep per ogni giorno toccato)
            day_cursor = start_tz.replace(hour=0, minute=0, second=0, microsecond=0)
            while day_cursor < end_tz:
                day_end = day_cursor + timedelta(days=1)
                seg_start = max(start_tz, day_cursor)
                seg_end = min(end_tz, day_end)
                if seg_end > seg_start:
                    day_key = day_cursor.date().isoformat()
                    if day_key in series_map:
                        s1 = (seg_start - day_cursor).total_seconds()
                        s2 = (seg_end - day_cursor).total_seconds()
                        series_map[day_key]["events"].append((s1, +1))
                        series_map[day_key]["events"].append((s2, -1))
                day_cursor = day_end

        # Costruzione output
        out_series: List[DayPoint] = []
        for d in day_keys:
            rec = series_map[d]
            # peak
            events: List[Tuple[float, int]] = rec["events"]  # type: ignore[assignment]
            events.sort(key=lambda x: (x[0], -x[1]))
            cur = 0
            peak = 0
            for _, delta in events:
                cur += delta
                if cur > peak:
                    peak = cur

            # media minuti
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

    except TypeError as e:
        # errore tipico naive/aware: ritorno in safe-mode ma spiego
        return SeriesResponse(
            range={
                "from": window_start_tz.isoformat(),
                "to": (window_end_tz - timedelta(microseconds=1)).isoformat(),
            },
            tz=tz,
            days=days,
            series=[
                DayPoint(t=(window_start_tz + timedelta(days=i)).date().isoformat())
                for i in range(days)
            ],
            note=f"safe-mode: TypeError (datetime naive/aware normalizzato).",
        )
    except Exception as e:
        # fallback safe-mode generico
        return SeriesResponse(
            range={
                "from": window_start_tz.isoformat(),
                "to": (window_end_tz - timedelta(microseconds=1)).isoformat(),
            },
            tz=tz,
            days=days,
            series=[
                DayPoint(t=(window_start_tz + timedelta(days=i)).date().isoformat())
                for i in range(days)
            ],
            note=f"safe-mode: {type(e).__name__}",
        )
