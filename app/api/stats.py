# app/routers/stats.py
from __future__ import annotations

import os
from datetime import datetime, date
from typing import Optional, Union, Literal
from uuid import UUID
from types import SimpleNamespace

from fastapi import APIRouter, Depends, Query, Request, HTTPException
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy import text, create_engine

router = APIRouter(tags=["Stats"])

# ---------- deps (usa reali se presenti, altrimenti fallback) ----------
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
        raise RuntimeError("DATABASE_URL non configurato")
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
            raise HTTPException(status_code=400, detail="Header X-Debug-User-Id non valido")
        return SimpleNamespace(id=user_id, role=role)
    return _dep

get_db = _real_get_db or _fallback_get_db()
current_user = _real_current_user or _fallback_current_user()
# ----------------------------------------------------------------------

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

def _series(db: Session, sql: str, params: dict):
    rows = db.execute(text(sql), params).mappings().all()
    return [{"t": r["t"], "v": int(r["v"]) if r["v"] is not None else 0} for r in rows]

# ----------------------------------------------------------------------
# Helpers per scegliere la migliore "fonte listeners"
# Ordine preferenze:
#  1) sessions.listeners_count
#  2) joins (conteggio join per sessione)
#  3) events.payload->>'listeners_count' (session_ended)
# Forniamo tutti i pezzetti (CTE/join/expressions) necessari per KPI e serie
# ----------------------------------------------------------------------
def _listeners_source_snippets(db: Session, scope_where_prefix: str = "s.", scoped: bool = False):
    has_listeners  = _has_col(db, "sessions", "listeners_count")
    has_joins_tbl  = _table_exists(db, "joins")
    has_events_tbl = _table_exists(db, "events")
    has_events_payload = has_events_tbl and _has_col(db, "events", "payload") and _has_col(db, "events", "type")

    # Default: nessuna fonte
    ctes = []
    joins = ""
    total_expr = "0::int"
    series_expr = "0::int"
    avg_expr = "0.0::numeric(10,2)"
    max_expr = "0::int"

    if has_listeners:
        total_expr = "COALESCE(SUM(s.listeners_count),0)::int"
        series_expr = "COALESCE(SUM(s.listeners_count),0)::int"
        avg_expr = "COALESCE(AVG(s.listeners_count)::numeric, 0.0)::numeric(10,2)"
        max_expr = "COALESCE(MAX(s.listeners_count),0)::int"

    elif has_joins_tbl:
        # Conta join per sessione
        cte_joins = """
        joins_count AS (
            SELECT j.session_id, COUNT(*)::int AS listeners_count
            FROM joins j
            GROUP BY j.session_id
        )
        """
        ctes.append(cte_joins.strip())
        joins = "LEFT JOIN joins_count jc ON jc.session_id = s.id"
        total_expr = "COALESCE(SUM(jc.listeners_count),0)::int"
        series_expr = "COALESCE(SUM(jc.listeners_count),0)::int"
        avg_expr = "COALESCE(AVG(jc.listeners_count)::numeric, 0.0)::numeric(10,2)"
        max_expr = "COALESCE(MAX(jc.listeners_count),0)::int"

    elif has_events_payload:
        # Estrae listeners_count dagli eventi di tipo session_ended
        cte_events_listeners = """
        events_listeners AS (
            SELECT e.session_id, MAX( (e.payload->>'listeners_count')::int ) AS listeners_count
            FROM events e
            WHERE e.type = 'session_ended'
            GROUP BY e.session_id
        )
        """
        ctes.append(cte_events_listeners.strip())
        joins = "LEFT JOIN events_listeners el ON el.session_id = s.id"
        total_expr = "COALESCE(SUM(el.listeners_count),0)::int"
        series_expr = "COALESCE(SUM(el.listeners_count),0)::int"
        avg_expr = "COALESCE(AVG(el.listeners_count)::numeric, 0.0)::numeric(10,2)"
        max_expr = "COALESCE(MAX(el.listeners_count),0)::int"

    return {
        "ctes": ctes,
        "joins": joins,
        "total_expr": total_expr,
        "series_expr": series_expr,
        "avg_expr": avg_expr,
        "max_expr": max_expr,
    }

# ----------------------------------------------------------------------

@router.get("/api/admin/stats", summary="Stats piattaforma (admin)")
def admin_stats(
    from_: Optional[Union[date, datetime]] = Query(None, alias="from"),
    to: Optional[Union[date, datetime]] = Query(None),
    bucket: Literal["hour", "day", "week", "month"] = "day",
    db: Session = Depends(get_db),
    user = Depends(current_user),
):
    if getattr(user, "role", None) != "admin":
        return {"error": "admin_only"}

    if not _table_exists(db, "sessions"):
        return {
            "range": {"from": str(from_) if from_ else None, "to": str(to) if to else None, "bucket": bucket},
            "kpi": {"sessions_total": 0, "listeners_total": 0, "avg_session_minutes": 0.0, "peak_concurrency": 0,
                    "avg_listeners": 0.0, "max_listeners": 0},
            "series": {"sessions": [], "listeners": []},
        }

    # feature detection
    has_started_at = _has_col(db, "sessions", "started_at")
    has_ended_at   = _has_col(db, "sessions", "ended_at")
    has_peak       = _has_col(db, "sessions", "peak_concurrency")
    has_events     = _table_exists(db, "events")

    # WHERE dinamico
    params, where = {}, " WHERE 1=1"
    if from_ and has_started_at:
        where += " AND s.started_at >= :from_"; params["from_"] = from_
    if to and has_started_at:
        where += " AND s.started_at < :to"; params["to"] = to

    # KPI: avg_session_minutes (preferendo colonna ended_at, fallback eventi session_ended)
    if has_ended_at and has_started_at:
        avg_minutes_sql = "COALESCE(AVG(EXTRACT(EPOCH FROM (s.ended_at - s.started_at)))/60.0,0)::numeric(10,2)"
        ended_cte = ""
        ended_join = ""
    elif has_events and has_started_at:
        avg_minutes_sql = """
        COALESCE(AVG(EXTRACT(EPOCH FROM (se.ended_at - s.started_at)))/60.0,0)::numeric(10,2)
        """
        ended_cte = """
        ended AS (
            SELECT e.session_id, MAX(e.created_at) AS ended_at
            FROM events e
            WHERE e.type = 'session_ended'
            GROUP BY e.session_id
        )
        """
        ended_join = "LEFT JOIN ended se ON se.session_id = s.id"
    else:
        avg_minutes_sql = "0.0::numeric(10,2)"
        ended_cte = ""
        ended_join = ""

    peak_sql = "COALESCE(MAX(s.peak_concurrency),0)::int" if has_peak else "0::int"

    # Sorgente listeners (sessions / joins / events.payload)
    listeners_src = _listeners_source_snippets(db)
    ctes = []
    if ended_cte.strip(): ctes.append(ended_cte.strip())
    ctes.extend(listeners_src["ctes"])
    with_cte = ("WITH " + ",\n".join(ctes)) if ctes else ""
    listeners_total_sql = listeners_src["total_expr"]
    listeners_series_val = listeners_src["series_expr"]
    avg_listeners_sql = listeners_src["avg_expr"]
    max_listeners_sql = listeners_src["max_expr"]

    # KPI query
    kpi_sql = f"""
      {with_cte}
      SELECT
        COUNT(*)::int AS sessions_total,
        {listeners_total_sql} AS listeners_total,
        {avg_minutes_sql} AS avg_session_minutes,
        {peak_sql} AS peak_concurrency,
        {avg_listeners_sql} AS avg_listeners,
        {max_listeners_sql} AS max_listeners
      FROM sessions s
      {ended_join}
      {listeners_src["joins"]}
      {where}
    """
    kpi = db.execute(text(kpi_sql), params).mappings().one()

    # Serie temporali (se manca started_at → vuote)
    if has_started_at:
        trunc = {"hour":"hour","day":"day","week":"week","month":"month"}[bucket]
        series_sessions_sql = f"""
          SELECT to_char(date_trunc('{trunc}', s.started_at), 'YYYY-MM-DD') AS t,
                 COUNT(*)::int AS v
          FROM sessions s
          {where}
          GROUP BY 1 ORDER BY 1
        """
        # listeners: somma per bucket dalla stessa sorgente scelta
        # (se richiede CTE, lo ripetiamo nello statement)
        if listeners_src["joins"]:
            series_listeners_sql = f"""
              {("WITH " + ", ".join(listeners_src["ctes"])) if listeners_src["ctes"] else ""}
              SELECT to_char(date_trunc('{trunc}', s.started_at), 'YYYY-MM-DD') AS t,
                     {listeners_series_val} AS v
              FROM sessions s
              {listeners_src["joins"]}
              {where}
              GROUP BY 1 ORDER BY 1
            """
        else:
            series_listeners_sql = f"""
              SELECT to_char(date_trunc('{trunc}', s.started_at), 'YYYY-MM-DD') AS t,
                     {listeners_series_val} AS v
              FROM sessions s
              {where}
              GROUP BY 1 ORDER BY 1
            """
        series_sessions = _series(db, series_sessions_sql, params)
        series_listeners = _series(db, series_listeners_sql, params)
    else:
        series_sessions, series_listeners = [], []

    return {
        "range": {"from": str(from_) if from_ else None, "to": str(to) if to else None, "bucket": bucket},
        "kpi": dict(kpi),
        "series": {"sessions": series_sessions, "listeners": series_listeners},
    }

# ----------------------------------------------------------------------

@router.get("/api/guides/me/stats", summary="Stats guida (scoped)")
def guide_stats(
    from_: Optional[Union[date, datetime]] = Query(None, alias="from"),
    to: Optional[Union[date, datetime]] = Query(None),
    bucket: Literal["hour","day","week","month"] = "day",
    db: Session = Depends(get_db),
    user = Depends(current_user),
):
    if not _table_exists(db, "sessions"):
        return {"error": "no_sessions_table"}

    has_started_at = _has_col(db, "sessions", "started_at")
    has_ended_at   = _has_col(db, "sessions", "ended_at")
    has_peak       = _has_col(db, "sessions", "peak_concurrency")
    has_guide_id   = _has_col(db, "sessions", "guide_id")
    has_events     = _table_exists(db, "events")

    if not has_guide_id:
        return {"error": "guide_id_not_available"}

    params, where = {"guide_id": str(user.id)}, " WHERE s.guide_id = :guide_id"
    if from_ and has_started_at:
        where += " AND s.started_at >= :from_"; params["from_"] = from_
    if to and has_started_at:
        where += " AND s.started_at < :to"; params["to"] = to

    # avg_session_minutes (scoped)
    if has_ended_at and has_started_at:
        avg_minutes_sql = "COALESCE(AVG(EXTRACT(EPOCH FROM (s.ended_at - s.started_at)))/60.0,0)::numeric(10,2)"
        ended_cte = ""
        ended_join = ""
    elif has_events and has_started_at:
        avg_minutes_sql = """
        COALESCE(AVG(EXTRACT(EPOCH FROM (se.ended_at - s.started_at)))/60.0,0)::numeric(10,2)
        """
        ended_cte = """
        ended AS (
            SELECT e.session_id, MAX(e.created_at) AS ended_at
            FROM events e
            WHERE e.type = 'session_ended'
            GROUP BY e.session_id
        )
        """
        ended_join = "LEFT JOIN ended se ON se.session_id = s.id"
    else:
        avg_minutes_sql = "0.0::numeric(10,2)"
        ended_cte = ""
        ended_join = ""

    peak_sql = "COALESCE(MAX(s.peak_concurrency),0)::int" if has_peak else "0::int"

    # Sorgente listeners consistente con l'admin
    listeners_src = _listeners_source_snippets(db, scoped=True)
    ctes = []
    if ended_cte.strip(): ctes.append(ended_cte.strip())
    ctes.extend(listeners_src["ctes"])
    with_cte = ("WITH " + ",\n".join(ctes)) if ctes else ""
    listeners_total_sql = listeners_src["total_expr"]
    listeners_series_val = listeners_src["series_expr"]
    avg_listeners_sql = listeners_src["avg_expr"]
    max_listeners_sql = listeners_src["max_expr"]

    kpi_sql = f"""
      {with_cte}
      SELECT
        COUNT(*)::int AS sessions_total,
        {listeners_total_sql} AS listeners_total,
        {avg_minutes_sql} AS avg_session_minutes,
        {peak_sql} AS peak_concurrency,
        {avg_listeners_sql} AS avg_listeners,
        {max_listeners_sql} AS max_listeners
      FROM sessions s
      {ended_join}
      {listeners_src["joins"]}
      {where}
    """
    kpi = db.execute(text(kpi_sql), params).mappings().one()

    if has_started_at:
        trunc = {"hour":"hour","day":"day","week":"week","month":"month"}[bucket]
        if listeners_src["joins"]:
            series_listeners_sql = f"""
              {("WITH " + ", ".join(listeners_src["ctes"])) if listeners_src["ctes"] else ""}
              SELECT to_char(date_trunc('{trunc}', s.started_at), 'YYYY-MM-DD') AS t,
                     {listeners_series_val} AS v
              FROM sessions s
              {listeners_src["joins"]}
              {where}
              GROUP BY 1 ORDER BY 1
            """
        else:
            series_listeners_sql = f"""
              SELECT to_char(date_trunc('{trunc}', s.started_at), 'YYYY-MM-DD') AS t,
                     {listeners_series_val} AS v
              FROM sessions s
              {where}
              GROUP BY 1 ORDER BY 1
            """
        series_sessions_sql = f"""
          SELECT to_char(date_trunc('{trunc}', s.started_at), 'YYYY-MM-DD') AS t,
                 COUNT(*)::int AS v
          FROM sessions s
          {where}
          GROUP BY 1 ORDER BY 1
        """
        series_sessions = _series(db, series_sessions_sql, params)
        series_listeners = _series(db, series_listeners_sql, params)
    else:
        series_sessions, series_listeners = [], []

    return {
        "range": {"from": str(from_) if from_ else None, "to": str(to) if to else None, "bucket": bucket},
        "kpi": dict(kpi),
        "series": {"sessions": series_sessions, "listeners": series_listeners},
    }
