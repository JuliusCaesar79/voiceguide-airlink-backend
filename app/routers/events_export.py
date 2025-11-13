# app/routers/events_export.py
from __future__ import annotations

import os, csv, io
from datetime import datetime, date
from typing import Optional, Iterable, Union
from uuid import UUID
from types import SimpleNamespace

from fastapi import APIRouter, Depends, Query, Request, HTTPException
from fastapi.responses import StreamingResponse, PlainTextResponse
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy import text, create_engine

# Tag uniforme per sezione admin
router = APIRouter(tags=["admin"])

# ---------- DEPENDENCIES (usa le reali se presenti, altrimenti fallback) ----------
def _wire_real_deps():
    candidates = [
        ("app.dependencies", "get_db", "current_user"),
        ("app.api.dependencies", "get_db", "current_user"),
        ("app.api.deps", "get_db", "current_user"),
        ("app.core.dependencies", "get_db", "current_user"),
    ]
    for mod_name, gdb, cu in candidates:
        try:
            mod = __import__(mod_name, fromlist=[gdb, cu])
            return getattr(mod, gdb), getattr(mod, cu)
        except Exception:
            continue
    return None, None

_real_get_db, _real_current_user = _wire_real_deps()

def _fallback_get_db():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL non configurato nell'ambiente.")
    engine = create_engine(db_url, future=True)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    def _dep():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()
    return _dep

def _fallback_current_user():
    def _dep(request: Request):
        role = request.headers.get("x-debug-role", "admin").lower()
        uid = request.headers.get("x-debug-user-id", "00000000-0000-0000-0000-000000000000")
        try:
            user_id = UUID(uid)
        except Exception:
            raise HTTPException(status_code=400, detail="Header X-Debug-User-Id non è un UUID valido")
        return SimpleNamespace(id=user_id, role=role)
    return _dep

get_db = _real_get_db or _fallback_get_db()
current_user = _real_current_user or _fallback_current_user()
# -------------------------------------------------------------------------------

def _iter_csv(rows_iter: Iterable[dict], include_header: bool = True):
    out = io.StringIO()
    w = csv.writer(out, quoting=csv.QUOTE_MINIMAL)
    wrote = False
    for idx, row in enumerate(rows_iter):
        if include_header and not wrote:
            w.writerow(list(row.keys()))
            yield out.getvalue(); out.seek(0); out.truncate(0)
            wrote = True
        w.writerow(list(row.values()))
        if idx % 500 == 0:
            yield out.getvalue(); out.seek(0); out.truncate(0)
    yield out.getvalue()

def _has_col(db: Session, table: str, col: str) -> bool:
    q = text("""
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = :t AND column_name = :c
        LIMIT 1
    """)
    return db.execute(q, {"t": table, "c": col}).first() is not None

def _table_exists(db: Session, table: str) -> bool:
    q = text("""
        SELECT 1
        FROM information_schema.tables
        WHERE table_name = :t
        LIMIT 1
    """)
    return db.execute(q, {"t": table}).first() is not None

@router.get(
    "/api/events/export.csv",
    tags=["admin"],
    name="export_events_csv",
    operation_id="export_events_csv",
    response_class=PlainTextResponse,
    summary="Esporta eventi/sessioni in CSV"
)
def export_events_csv(
    from_: Optional[Union[datetime, date]] = Query(None, alias="from"),
    to: Optional[Union[datetime, date]] = Query(None),
    guide_id: Optional[UUID] = Query(None),
    include_joins: bool = Query(False),
    db: Session = Depends(get_db),
    user = Depends(current_user),
):
    # RBAC: se non admin, filtra per la guida corrente
    if getattr(user, "role", None) != "admin":
        guide_id = user.id

    # --- feature detection ---
    if not _table_exists(db, "sessions"):
        def rows_empty():
            yield {"info": "sessions table not found in this schema"}
        return StreamingResponse(
            _iter_csv(rows_empty()), media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=events_empty.csv"}
        )

    # sessions columns
    has_started_at = _has_col(db, "sessions", "started_at")
    has_ended_at   = _has_col(db, "sessions", "ended_at")
    has_expires_at = _has_col(db, "sessions", "expires_at")  # NEW: fallback
    has_listeners  = _has_col(db, "sessions", "listeners_count")
    has_peak       = _has_col(db, "sessions", "peak_concurrency")
    has_status     = _has_col(db, "sessions", "status")
    has_guide_id   = _has_col(db, "sessions", "guide_id")
    has_tour_id    = _has_col(db, "sessions", "tour_id")
    has_pin        = _has_col(db, "sessions", "pin")
    has_s_license  = _has_col(db, "sessions", "license_code")

    # ancillary tables
    has_events     = _table_exists(db, "events")
    has_joins      = _table_exists(db, "joins")
    has_e_license  = has_events and _has_col(db, "events", "license_code")
    has_e_payload  = has_events and _has_col(db, "events", "payload")

    params = {}
    time_from, time_to, guide_filter = "", "", ""
    if from_ and has_started_at:
        time_from = " AND s.started_at >= :from_"
        params["from_"] = from_
    if to and has_started_at:
        time_to = " AND s.started_at < :to"
        params["to"] = to
    if guide_id and has_guide_id:
        guide_filter = " AND s.guide_id = :guide_id"
        params["guide_id"] = str(guide_id)

    # ==============================
    # Modalità JOINS (dettaglio)
    # ==============================
    if include_joins:
        if not has_joins:
            def rows_empty():
                yield {"info": "joins table not found in this schema"}
            return StreamingResponse(
                _iter_csv(rows_empty()), media_type="text/csv; charset=utf-8",
                headers={"Content-Disposition": "attachment; filename=events_joins.csv"}
            )

        # join columns detection
        j_has_joined_at = _has_col(db, "joins", "joined_at")
        j_has_left_at   = _has_col(db, "joins", "left_at")
        j_has_version   = _has_col(db, "joins", "client_version")
        j_has_device    = _has_col(db, "joins", "device")
        j_has_quality   = _has_col(db, "joins", "network_quality")
        j_has_city      = _has_col(db, "joins", "city")
        j_has_country   = _has_col(db, "joins", "country")

        # ended_at fallback: sessions.ended_at -> sessions.expires_at -> events -> NULL
        ended_col = "s.ended_at" if has_ended_at else ("s.expires_at" if has_expires_at else None)
        ended_cte = ""
        ended_join = ""
        if not ended_col and has_events:
            ended_cte = """
            ended AS (
                SELECT e.session_id, MAX(e.created_at) AS ended_at
                FROM events e
                WHERE e.type = 'session_ended'
                GROUP BY e.session_id
            )
            """
            ended_join = "LEFT JOIN ended se ON se.session_id = s.id"
            ended_col = "se.ended_at"
        if not ended_col:
            ended_col = "NULL::timestamp"

        listen_seconds = (
            "COALESCE(EXTRACT(EPOCH FROM (j.left_at - j.joined_at)),0)::bigint"
            if j_has_joined_at and j_has_left_at else "NULL::bigint"
        )

        with_cte = f"WITH {ended_cte.strip()}" if ended_cte.strip() else ""

        sql = f"""
            {with_cte}
            SELECT
              s.id AS session_id,
              j.id AS join_id,
              {"s.started_at" if has_started_at else "NULL::timestamp"} AS started_at,
              {ended_col} AS ended_at,
              {"j.joined_at" if j_has_joined_at else "NULL::timestamp"} AS joined_at,
              {"j.left_at" if j_has_left_at else "NULL::timestamp"} AS left_at,
              {listen_seconds} AS listen_seconds,
              {"j.client_version" if j_has_version else "NULL::text"} AS client_version,
              {"j.device" if j_has_device else "NULL::text"} AS listener_device,
              {"j.network_quality" if j_has_quality else "NULL::text"} AS network_quality,
              {"j.city" if j_has_city else "NULL::text"} AS city,
              {"j.country" if j_has_country else "NULL::text"} AS country,
              {"s.pin" if has_pin else "NULL::text"} AS pin,
              {"s.guide_id" if has_guide_id else "NULL::uuid"} AS guide_id,
              {"s.license_code" if has_s_license else ("se2.license_code" if has_e_license else "NULL::text")} AS license_code
            FROM joins j
            JOIN sessions s ON s.id = j.session_id
            {ended_join}
            {("LEFT JOIN (SELECT session_id, MAX(license_code) AS license_code FROM events GROUP BY session_id) se2 ON se2.session_id = s.id") if (not has_s_license and has_e_license) else ""}
            WHERE 1=1 {time_from} {time_to} {guide_filter}
            ORDER BY {"s.started_at" if has_started_at else "j.joined_at"} DESC
        """

    # ==============================
    # Modalità SESSIONS (riassunto)
    # ==============================
    else:
        # ended_at fallback: sessions.ended_at -> sessions.expires_at -> events -> NULL
        ended_cte, ended_join = "", ""
        if has_ended_at:
            ended_col = "s.ended_at"
        elif has_expires_at:
            ended_col = "s.expires_at"
        elif has_events:
            ended_cte = """
            ended AS (
                SELECT e.session_id, MAX(e.created_at) AS ended_at
                FROM events e
                WHERE e.type = 'session_ended'
                GROUP BY e.session_id
            )
            """
            ended_join = "LEFT JOIN ended se ON se.session_id = s.id"
            ended_col = "se.ended_at"
        else:
            ended_col = "NULL::timestamp"

        # --- listeners_count: precedence sessions -> joins -> events.payload
        listeners_expr = "s.listeners_count" if has_listeners else "NULL::int"
        listeners_cte, listeners_join = "", ""
        if not has_listeners and has_joins:
            listeners_cte = """
            joins_count AS (
                SELECT j.session_id, COUNT(*)::int AS listeners_count
                FROM joins j
                GROUP BY j.session_id
            )
            """
            listeners_join = "LEFT JOIN joins_count jc ON jc.session_id = s.id"
            listeners_expr = "jc.listeners_count"
        elif not has_listeners and (has_events and has_e_payload):
            listeners_cte = """
            events_listeners AS (
                SELECT e.session_id, MAX( (e.payload->>'listeners_count')::int ) AS listeners_count
                FROM events e
                WHERE e.type = 'session_ended'
                GROUP BY session_id
            )
            """
            listeners_join = "LEFT JOIN events_listeners el ON el.session_id = s.id"
            listeners_expr = "el.listeners_count"

        # altre colonne opzionali
        peak_col      = "s.peak_concurrency" if has_peak else "NULL::int"
        status_col    = "s.status" if has_status else "NULL::text"
        guide_col     = "s.guide_id" if has_guide_id else "NULL::uuid"
        tour_col      = "s.tour_id" if has_tour_id else "NULL::uuid"
        license_col   = "s.license_code" if has_s_license else ("se2.license_code" if has_e_license else "NULL::text")

        # CTE finali (ended + listeners + (opz) license da events)
        ctes = []
        if ended_cte.strip():
            ctes.append(ended_cte.strip())
        if listeners_cte.strip():
            ctes.append(listeners_cte.strip())
        if not has_s_license and has_e_license:
            ctes.append("""
            events_license AS (
                SELECT session_id, MAX(license_code) AS license_code
                FROM events
                GROUP BY session_id
            )
            """.strip())

        with_cte = ("WITH " + ",\n            ".join(ctes)) if ctes else ""
        license_join = ("LEFT JOIN events_license se2 ON se2.session_id = s.id") if (not has_s_license and has_e_license) else ""

        sql = f"""
            {with_cte}
            SELECT
              s.id AS session_id,
              {"s.started_at" if has_started_at else "NULL::timestamp"} AS started_at,
              {ended_col} AS ended_at,
              CASE
                 WHEN {ended_col} IS NULL OR {"s.started_at IS NULL" if not has_started_at else "FALSE"} THEN NULL
                 ELSE COALESCE(EXTRACT(EPOCH FROM ({ended_col} - s.started_at)),0)::bigint
              END AS duration_seconds,
              {guide_col} AS guide_id,
              {tour_col} AS tour_id,
              {license_col} AS license_code,
              {listeners_expr} AS listeners_count,
              {peak_col} AS peak_concurrency,
              {status_col} AS status
            FROM sessions s
            {ended_join}
            {listeners_join}
            {license_join}
            WHERE 1=1 {time_from} {time_to} {guide_filter}
            ORDER BY {"s.started_at" if has_started_at else "s.id"} DESC
        """

    def row_iter():
        res = db.execute(text(sql), params)
        for r in res.mappings():
            yield dict(r)

    # filename
    f_from = (str(from_).replace(":", "-").replace(" ", "_")) if from_ else "all"
    f_to   = (str(to).replace(":", "-").replace(" ", "_"))   if to   else "now"
    fname = "events.csv" if (f_from == "all" and f_to == "now") else f"events_{f_from}_{f_to}.csv"

    hdrs = {"Content-Disposition": f"attachment; filename={fname}"}
    return StreamingResponse(_iter_csv(row_iter()), media_type="text/csv; charset=utf-8", headers=hdrs)


# -------------------------------------------------------------------
# Nuove rotte senza conflitti (riusano la funzione principale)
# -------------------------------------------------------------------

@router.get(
    "/api/admin/export.sessions.csv",
    tags=["admin"],
    name="export_sessions_csv",
    operation_id="export_sessions_csv",
    response_class=PlainTextResponse,
    summary="Esporta SESSIONI (riassunto) in CSV"
)
def export_sessions_csv(
    from_: Optional[Union[datetime, date]] = Query(None, alias="from"),
    to: Optional[Union[datetime, date]] = Query(None),
    guide_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    user = Depends(current_user),
):
    return export_events_csv(from_=from_, to=to, guide_id=guide_id, include_joins=False, db=db, user=user)


@router.get(
    "/api/admin/export.joins.csv",
    tags=["admin"],
    name="export_joins_csv",
    operation_id="export_joins_csv",
    response_class=PlainTextResponse,
    summary="Esporta JOINS (dettaglio connessioni) in CSV"
)
def export_joins_csv(
    from_: Optional[Union[datetime, date]] = Query(None, alias="from"),
    to: Optional[Union[datetime, date]] = Query(None),
    guide_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    user = Depends(current_user),
):
    return export_events_csv(from_=from_, to=to, guide_id=guide_id, include_joins=True, db=db, user=user)
