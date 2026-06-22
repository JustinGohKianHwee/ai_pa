import os
from datetime import datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.db.supabase_client import SupabaseConfigurationError, get_supabase_client
from app.security import require_dev_admin_token

router = APIRouter(tags=["daily_review"])

_KNOWN_TYPES = {"task", "finance", "food", "calendar", "note", "journal", "investment"}


class InboxItemSummary(BaseModel):
    id: str
    item_type: str
    review_status: str
    title: Optional[str] = None
    created_at: str
    reviewed_at: Optional[str] = None


class ConfirmedByType(BaseModel):
    task: int = 0
    finance: int = 0
    food: int = 0
    calendar: int = 0
    note: int = 0
    journal: int = 0
    investment: int = 0
    other: int = 0


class DailyReviewResponse(BaseModel):
    review_date: str
    timezone: str
    captured_count: int
    confirmed_count: int
    rejected_count: int
    pending_count: int
    confirmed_by_type: ConfirmedByType
    captured_items: list[InboxItemSummary]
    confirmed_items: list[InboxItemSummary]
    rejected_items: list[InboxItemSummary]
    pending_items: list[InboxItemSummary]
    summary: str


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


def _count_by_type(items: list[dict]) -> ConfirmedByType:
    counts: dict[str, int] = {t: 0 for t in _KNOWN_TYPES}
    counts["other"] = 0
    for item in items:
        t = item.get("item_type", "")
        if t in _KNOWN_TYPES:
            counts[t] += 1
        else:
            counts["other"] += 1
    return ConfirmedByType(**counts)


def _type_breakdown(by_type: ConfirmedByType) -> str:
    labels = [
        (by_type.task,       "task"),
        (by_type.finance,    "finance item"),
        (by_type.food,       "food log"),
        (by_type.calendar,   "calendar intent"),
        (by_type.note,       "note"),
        (by_type.journal,    "journal entry"),
        (by_type.investment, "investment note"),
        (by_type.other,      "other item"),
    ]
    return ", ".join(
        f"{n} {label}{'s' if n != 1 else ''}" for n, label in labels if n > 0
    )


def _build_summary(
    captured: int,
    confirmed: int,
    rejected: int,
    pending: int,
    by_type: ConfirmedByType,
) -> str:
    if captured == 0 and confirmed == 0 and rejected == 0:
        return "Nothing captured or reviewed today."
    parts = []
    if captured:
        parts.append(f"{captured} item{'s' if captured != 1 else ''} captured")
    if confirmed:
        breakdown = _type_breakdown(by_type)
        parts.append(
            f"{confirmed} confirmed" + (f" ({breakdown})" if breakdown else "")
        )
    if rejected:
        parts.append(f"{rejected} rejected")
    if pending:
        parts.append(f"{pending} awaiting review")
    return ". ".join(parts).capitalize() + "."


@router.get("/daily_review", dependencies=[Depends(require_dev_admin_token)])
def get_daily_review(
    date: Optional[str] = Query(default=None),
) -> DailyReviewResponse:
    if date is not None and date != "today":
        raise HTTPException(
            status_code=422,
            detail="Only 'today' is supported for the date parameter.",
        )

    user_tz, tz_name = _resolve_timezone()

    now_local = datetime.now(user_tz)
    today_local = now_local.date()
    start_local = datetime.combine(today_local, time.min, tzinfo=user_tz)
    end_local = start_local + timedelta(days=1)
    start_utc = start_local.astimezone(timezone.utc)
    end_utc = end_local.astimezone(timezone.utc)
    review_date = today_local.isoformat()

    try:
        client = get_supabase_client()
    except SupabaseConfigurationError as exc:
        raise HTTPException(status_code=500, detail=f"Database configuration error: {exc}")

    inbox_cols = "id, item_type, review_status, title, created_at, reviewed_at"

    # Q1 — captured today: capture_events.created_at in window, embedded inbox_items
    try:
        cap_result = (
            client.table("capture_events")
            .select(f"id, created_at, source, inbox_items({inbox_cols})")
            .gte("created_at", start_utc.isoformat())
            .lt("created_at", end_utc.isoformat())
            .order("created_at", desc=True)
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database query failed") from exc

    # Extract inbox_items embedded in each capture_event row
    captured_items: list[InboxItemSummary] = []
    for row in cap_result.data:
        embedded = row.get("inbox_items") or []
        if embedded:
            captured_items.append(InboxItemSummary(**embedded[0]))

    pending_items = [
        item
        for item in captured_items
        if item.review_status in ("pending", "needs_manual_classification")
    ]

    # Q2 — confirmed today: inbox_items.reviewed_at in window, review_status='confirmed'
    # Q3 — rejected today: inbox_items.reviewed_at in window, review_status='rejected'
    try:
        conf_result = (
            client.table("inbox_items")
            .select(inbox_cols)
            .gte("reviewed_at", start_utc.isoformat())
            .lt("reviewed_at", end_utc.isoformat())
            .eq("review_status", "confirmed")
            .order("reviewed_at", desc=True)
            .execute()
        )
        rej_result = (
            client.table("inbox_items")
            .select(inbox_cols)
            .gte("reviewed_at", start_utc.isoformat())
            .lt("reviewed_at", end_utc.isoformat())
            .eq("review_status", "rejected")
            .order("reviewed_at", desc=True)
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database query failed") from exc

    confirmed_items = [InboxItemSummary(**row) for row in conf_result.data]
    rejected_items = [InboxItemSummary(**row) for row in rej_result.data]

    captured_count = len(cap_result.data)
    confirmed_count = len(confirmed_items)
    rejected_count = len(rejected_items)
    pending_count = len(pending_items)

    by_type = _count_by_type(conf_result.data)
    summary = _build_summary(captured_count, confirmed_count, rejected_count, pending_count, by_type)

    return DailyReviewResponse(
        review_date=review_date,
        timezone=tz_name,
        captured_count=captured_count,
        confirmed_count=confirmed_count,
        rejected_count=rejected_count,
        pending_count=pending_count,
        confirmed_by_type=by_type,
        captured_items=captured_items,
        confirmed_items=confirmed_items,
        rejected_items=rejected_items,
        pending_items=pending_items,
        summary=summary,
    )
