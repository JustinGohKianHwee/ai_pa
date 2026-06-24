"""
Financial Intelligence summary (Phase 22a) — read only, deterministic.

Assembles the per-currency summary from: the latest manual financial snapshot, the latest
portfolio snapshot, and confirmed money_events expenses. All numbers come from stored data;
missing inputs yield "unavailable" (None) — never fabricated. No advice, no cross-currency total.

Monthly expense windows use money_events.created_at with USER_TIMEZONE local-month boundaries
(NOT the free-text occurred_at):
  * current month  = created within the current local calendar month
  * trailing 3 mo  = created within the window starting on the 1st of (current month - 2),
                     summed and divided by 3 for the average.
"""
import os
from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.db.supabase_client import SupabaseConfigurationError, get_supabase_client
from app.security import require_user
from app.services.financial_intelligence import compute_monthly, compute_summary

router = APIRouter(prefix="/financial_intelligence", tags=["financial_intelligence"])

_SNAPSHOT_SELECT = (
    "snapshot_date,partial_failure,"
    "portfolio_snapshot_currency_totals("
    "currency,market_value,cash_value,invested_value,total_value,"
    "market_value_complete,market_value_missing)"
)


class FinancialIntelligenceSummary(BaseModel):
    currencies: list[dict]
    portfolio_as_of: str | None = None
    portfolio_partial: bool | None = None
    manual_as_of: str | None = None
    has_manual_snapshot: bool = False


class MonthlyExplanation(BaseModel):
    month: str
    prev_month: str
    has_previous_month: bool
    currencies: list[dict]


def _month_starts(tz: ZoneInfo) -> tuple[str, str, str]:
    """Return (trailing_start_utc, current_month_start_utc, next_month_start_utc) as ISO."""
    today = datetime.now(tz).date()
    y, m = today.year, today.month

    cur = datetime(y, m, 1, tzinfo=tz)

    nm, ny = (1, y + 1) if m == 12 else (m + 1, y)
    nxt = datetime(ny, nm, 1, tzinfo=tz)

    tm, ty = m - 2, y
    while tm <= 0:
        tm += 12
        ty -= 1
    trailing = datetime(ty, tm, 1, tzinfo=tz)

    to_utc = lambda d: d.astimezone(timezone.utc).isoformat()
    return to_utc(trailing), to_utc(cur), to_utc(nxt)


def _expenses_by_currency(client, owner_id: str, start_utc: str, end_utc: str) -> dict[str, float]:
    """Sum confirmed expense money_events created in [start, end) by currency (Decimal)."""
    result = (
        client.table("money_events")
        .select("amount,currency")
        .eq("owner_id", owner_id)
        .eq("direction", "expense")
        .gte("created_at", start_utc)
        .lt("created_at", end_utc)
        .execute()
    )
    buckets: dict[str, Decimal] = {}
    for row in result.data or []:
        ccy = str(row.get("currency", "")).strip().upper()
        if not ccy:
            continue
        buckets[ccy] = buckets.get(ccy, Decimal("0")) + Decimal(str(row["amount"]))
    return {k: float(v) for k, v in buckets.items()}


@router.get("/summary", response_model=FinancialIntelligenceSummary)
def get_summary(owner_id: str = Depends(require_user)) -> FinancialIntelligenceSummary:
    try:
        client = get_supabase_client()
    except SupabaseConfigurationError as exc:
        raise HTTPException(status_code=500, detail=f"Database configuration error: {exc}")

    tz = ZoneInfo(os.getenv("USER_TIMEZONE", "UTC"))
    trailing_start, cur_start, next_start = _month_starts(tz)

    try:
        manual_res = (
            client.table("manual_financial_snapshots")
            .select("*")
            .eq("owner_id", owner_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        snap_res = (
            client.table("portfolio_snapshots")
            .select(
                "snapshot_date,partial_failure,"
                "portfolio_snapshot_currency_totals("
                "currency,market_value,cash_value,invested_value,total_value,"
                "market_value_complete,market_value_missing)"
            )
            .eq("owner_id", owner_id)
            .order("snapshot_date", desc=True)
            .limit(1)
            .execute()
        )
        current_month = _expenses_by_currency(client, owner_id, cur_start, next_start)
        trailing_total = _expenses_by_currency(client, owner_id, trailing_start, next_start)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database query failed") from exc

    manual = manual_res.data[0] if manual_res.data else None

    portfolio_totals: list[dict] = []
    portfolio_as_of = None
    portfolio_partial = None
    if snap_res.data:
        snap = snap_res.data[0]
        portfolio_as_of = str(snap["snapshot_date"])
        portfolio_partial = bool(snap["partial_failure"])
        portfolio_totals = snap.get("portfolio_snapshot_currency_totals") or []

    trailing_avg = {c: v / 3 for c, v in trailing_total.items()}

    summary = compute_summary(manual, portfolio_totals, current_month, trailing_avg)

    return FinancialIntelligenceSummary(
        currencies=summary["currencies"],
        portfolio_as_of=portfolio_as_of,
        portfolio_partial=portfolio_partial,
        manual_as_of=(manual.get("as_of") or manual.get("created_at")) if manual else None,
        has_manual_snapshot=manual is not None,
    )


def _month_windows(tz: ZoneInfo) -> tuple[str, str, str, str, str]:
    """Return (prev_start_utc, cur_start_utc, next_start_utc, month_label, prev_month_label)."""
    today = datetime.now(tz).date()
    y, m = today.year, today.month
    cur = datetime(y, m, 1, tzinfo=tz)
    nm, ny = (1, y + 1) if m == 12 else (m + 1, y)
    nxt = datetime(ny, nm, 1, tzinfo=tz)
    pm, py = (12, y - 1) if m == 1 else (m - 1, y)
    prev = datetime(py, pm, 1, tzinfo=tz)
    to_utc = lambda d: d.astimezone(timezone.utc).isoformat()
    return to_utc(prev), to_utc(cur), to_utc(nxt), cur.strftime("%B %Y"), prev.strftime("%B %Y")


def _portfolio_summary(row: dict) -> dict:
    return {
        "snapshot_date": str(row["snapshot_date"]),
        "partial_failure": bool(row["partial_failure"]),
        "currency_totals": row.get("portfolio_snapshot_currency_totals") or [],
    }


@router.get("/monthly", response_model=MonthlyExplanation)
def get_monthly(owner_id: str = Depends(require_user)) -> MonthlyExplanation:
    try:
        client = get_supabase_client()
    except SupabaseConfigurationError as exc:
        raise HTTPException(status_code=500, detail=f"Database configuration error: {exc}")

    tz = ZoneInfo(os.getenv("USER_TIMEZONE", "UTC"))
    prev_start, cur_start, next_start, month_label, prev_month_label = _month_windows(tz)

    try:
        current_month = _expenses_by_currency(client, owner_id, cur_start, next_start)
        # Previous-month comparison only if ≥1 expense was logged before the current month.
        history_res = (
            client.table("money_events")
            .select("id")
            .eq("owner_id", owner_id)
            .eq("direction", "expense")
            .lt("created_at", cur_start)
            .limit(1)
            .execute()
        )
        has_previous = bool(history_res.data)
        previous_month = (
            _expenses_by_currency(client, owner_id, prev_start, cur_start) if has_previous else None
        )
        manual_res = (
            client.table("manual_financial_snapshots")
            .select("*")
            .eq("owner_id", owner_id)
            .order("created_at", desc=True)
            .limit(2)
            .execute()
        )
        snap_res = (
            client.table("portfolio_snapshots")
            .select(_SNAPSHOT_SELECT)
            .eq("owner_id", owner_id)
            .order("snapshot_date", desc=True)
            .limit(2)
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database query failed") from exc

    manual_rows = manual_res.data or []
    income = {}
    if manual_rows:
        from app.services.financial_intelligence import _to_map

        income = _to_map(manual_rows[0].get("monthly_income_json"))
    manual_pair = (manual_rows[0], manual_rows[1]) if len(manual_rows) >= 2 else None

    snap_rows = snap_res.data or []
    portfolio_pair = (
        (_portfolio_summary(snap_rows[0]), _portfolio_summary(snap_rows[1]))
        if len(snap_rows) >= 2
        else None
    )

    result = compute_monthly(
        month_label, prev_month_label, current_month, previous_month,
        income, manual_pair, portfolio_pair,
    )
    return MonthlyExplanation(**result)
