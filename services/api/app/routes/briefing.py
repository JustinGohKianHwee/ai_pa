"""
Daily briefing & weekly reflection (Phase 24) — deterministic synthesis.

GET /briefing   — forward-looking daily briefing (focus, calendar, spend, portfolio delta, warnings).
GET /reflection — weekly reflection (wins, concerns, trends, progress).

Both compute live from confirmed records + snapshots + memory_events (no LLM — egress is gated at
Phase 27), then idempotently upsert the result into daily_summaries (one row per owner/date/kind) so
the artifact accrues for the future memory pipeline. Free-text dates (tasks.due_date,
calendar_intents.proposed_datetime) are NOT parsed: task focus uses the structured urgency field.
"""
import os
from datetime import datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.db.supabase_client import SupabaseConfigurationError, get_supabase_client
from app.routes.financial_intelligence import _expenses_by_currency, _month_starts
from app.security import require_user
from app.services.briefing import build_daily_briefing, build_weekly_reflection

router = APIRouter(tags=["briefing"])


class BriefingResponse(BaseModel):
    timezone: str
    briefing: dict


class ReflectionResponse(BaseModel):
    timezone: str
    reflection: dict


def _resolve_timezone() -> tuple[ZoneInfo, str]:
    tz_name = os.getenv("USER_TIMEZONE")
    if not tz_name:
        raise HTTPException(
            status_code=503,
            detail="USER_TIMEZONE is not configured. Set it in .env.local (e.g. Asia/Singapore).",
        )
    try:
        return ZoneInfo(tz_name), tz_name
    except ZoneInfoNotFoundError:
        raise HTTPException(
            status_code=503,
            detail=f"USER_TIMEZONE '{tz_name}' is not a valid IANA timezone identifier.",
        )


def _portfolio_delta(client, owner_id: str, before_date: Optional[str]) -> dict:
    """Per-currency total_value delta: latest snapshot minus the most recent baseline.

    before_date=None → baseline is the second-latest snapshot (daily view).
    before_date set  → baseline is the most recent snapshot strictly before that date (weekly view).
    Returns {currency: delta or None}; None when no baseline exists.
    """
    sel = "snapshot_date, portfolio_snapshot_currency_totals(currency, total_value)"
    latest_res = (
        client.table("portfolio_snapshots").select(sel)
        .eq("owner_id", owner_id).order("snapshot_date", desc=True).limit(1).execute()
    )
    if not latest_res.data:
        return {}
    latest = latest_res.data[0]

    if before_date is None:
        base_res = (
            client.table("portfolio_snapshots").select(sel)
            .eq("owner_id", owner_id).order("snapshot_date", desc=True).limit(2).execute()
        )
        baseline = base_res.data[1] if len(base_res.data) >= 2 else None
    else:
        base_res = (
            client.table("portfolio_snapshots").select(sel)
            .eq("owner_id", owner_id).lt("snapshot_date", before_date)
            .order("snapshot_date", desc=True).limit(1).execute()
        )
        baseline = base_res.data[0] if base_res.data else None

    def _totals(row: Optional[dict]) -> dict:
        out: dict[str, float] = {}
        for t in (row or {}).get("portfolio_snapshot_currency_totals") or []:
            out[str(t["currency"]).upper()] = float(t["total_value"])
        return out

    latest_tot = _totals(latest)
    base_tot = _totals(baseline)
    return {
        c: (round(latest_tot[c] - base_tot[c], 2) if c in base_tot else None)
        for c in latest_tot
    }


def _confirmed_by_domain(client, owner_id: str, start_utc: str, end_utc: str) -> dict:
    res = (
        client.table("memory_events").select("domain")
        .eq("owner_id", owner_id)
        .gte("occurred_at", start_utc).lt("occurred_at", end_utc)
        .execute()
    )
    counts: dict[str, int] = {}
    for row in res.data or []:
        d = row.get("domain")
        if d:
            counts[d] = counts.get(d, 0) + 1
    return counts


def _upsert_summary(client, owner_id: str, summary_date: str, kind: str, payload: dict) -> None:
    client.table("daily_summaries").upsert(
        {"owner_id": owner_id, "summary_date": summary_date, "kind": kind, "payload_json": payload},
        on_conflict="owner_id,summary_date,kind",
    ).execute()


@router.get("/briefing", response_model=BriefingResponse)
def get_briefing(owner_id: str = Depends(require_user)) -> BriefingResponse:
    tz, tz_name = _resolve_timezone()
    try:
        client = get_supabase_client()
    except SupabaseConfigurationError as exc:
        raise HTTPException(status_code=500, detail=f"Database configuration error: {exc}")

    today_local = datetime.now(tz).date()
    start_local = datetime.combine(today_local, time.min, tzinfo=tz)
    start_utc = start_local.astimezone(timezone.utc).isoformat()
    end_utc = (start_local + timedelta(days=1)).astimezone(timezone.utc).isoformat()
    _trailing, cur_month_start, next_month_start = _month_starts(tz)

    try:
        tasks_res = (
            client.table("tasks").select("id, title, urgency, due_date, status")
            .eq("owner_id", owner_id).eq("status", "open").execute()
        )
        cal_res = (
            client.table("calendar_intents").select("id, title, proposed_datetime, location")
            .eq("owner_id", owner_id).order("created_at", desc=True).limit(20).execute()
        )
        pending_res = (
            client.table("inbox_items").select("id", count="exact")
            .in_("review_status", ["pending", "needs_manual_classification"]).execute()
        )
        manual_res = (
            client.table("manual_financial_snapshots").select("monthly_income_json")
            .eq("owner_id", owner_id).order("created_at", desc=True).limit(1).execute()
        )
        spend_today = _expenses_by_currency(client, owner_id, start_utc, end_utc)
        spend_mtd = _expenses_by_currency(client, owner_id, cur_month_start, next_month_start)
        portfolio_delta = _portfolio_delta(client, owner_id, before_date=None)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database query failed") from exc

    pending_count = pending_res.count or 0
    manual = manual_res.data[0] if manual_res.data else None
    has_income = bool(manual and (manual.get("monthly_income_json") or []))

    briefing = build_daily_briefing(
        today=today_local.isoformat(),
        open_tasks=tasks_res.data or [],
        calendar_intents=cal_res.data or [],
        spend_today_by_ccy=spend_today,
        spend_mtd_by_ccy=spend_mtd,
        portfolio_delta_by_ccy=portfolio_delta,
        pending_count=pending_count,
        has_income_snapshot=has_income,
    )

    try:
        _upsert_summary(client, owner_id, today_local.isoformat(), "daily", briefing)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Could not persist the daily summary") from exc

    return BriefingResponse(timezone=tz_name, briefing=briefing)


@router.get("/reflection", response_model=ReflectionResponse)
def get_reflection(owner_id: str = Depends(require_user)) -> ReflectionResponse:
    tz, tz_name = _resolve_timezone()
    try:
        client = get_supabase_client()
    except SupabaseConfigurationError as exc:
        raise HTTPException(status_code=500, detail=f"Database configuration error: {exc}")

    today_local = datetime.now(tz).date()
    week_start = today_local - timedelta(days=6)  # 7-day window ending today (inclusive)
    prev_start = week_start - timedelta(days=7)

    def _utc(d) -> str:
        return datetime.combine(d, time.min, tzinfo=tz).astimezone(timezone.utc).isoformat()

    week_start_utc = _utc(week_start)
    week_end_utc = (datetime.combine(today_local, time.min, tzinfo=tz) + timedelta(days=1)).astimezone(timezone.utc).isoformat()
    prev_start_utc = _utc(prev_start)

    try:
        confirmed = _confirmed_by_domain(client, owner_id, week_start_utc, week_end_utc)
        spend_week = _expenses_by_currency(client, owner_id, week_start_utc, week_end_utc)
        spend_prev = _expenses_by_currency(client, owner_id, prev_start_utc, week_start_utc)
        goals_res = (
            client.table("goals").select("id, title, target, target_date")
            .eq("owner_id", owner_id).eq("status", "active").execute()
        )
        portfolio_delta_week = _portfolio_delta(client, owner_id, before_date=week_start.isoformat())
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database query failed") from exc

    reflection = build_weekly_reflection(
        week_start=week_start.isoformat(),
        week_end=today_local.isoformat(),
        confirmed_by_domain=confirmed,
        spend_week_by_ccy=spend_week,
        prev_week_spend_by_ccy=spend_prev,
        exercise_count=confirmed.get("exercise", 0),
        food_count=confirmed.get("food", 0),
        active_goals=goals_res.data or [],
        portfolio_delta_week_by_ccy=portfolio_delta_week,
    )

    try:
        _upsert_summary(client, owner_id, week_start.isoformat(), "weekly", reflection)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Could not persist the weekly summary") from exc

    return ReflectionResponse(timezone=tz_name, reflection=reflection)
