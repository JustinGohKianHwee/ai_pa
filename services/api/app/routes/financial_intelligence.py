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
from app.services.financial_intelligence import compute_summary

router = APIRouter(prefix="/financial_intelligence", tags=["financial_intelligence"])


class FinancialIntelligenceSummary(BaseModel):
    currencies: list[dict]
    portfolio_as_of: str | None = None
    portfolio_partial: bool | None = None
    manual_as_of: str | None = None
    has_manual_snapshot: bool = False


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


def _load_summary(client, owner_id: str) -> tuple[dict, dict | None, dict | None]:
    """Fetch inputs + run compute_summary. Returns (summary, snapshot_meta, manual_row).
    Raises HTTPException(503) on query failure."""
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
    snap_meta = None
    portfolio_totals: list[dict] = []
    if snap_res.data:
        snap = snap_res.data[0]
        snap_meta = {
            "as_of": str(snap["snapshot_date"]),
            "partial": bool(snap["partial_failure"]),
        }
        portfolio_totals = snap.get("portfolio_snapshot_currency_totals") or []

    trailing_avg = {c: v / 3 for c, v in trailing_total.items()}
    summary = compute_summary(manual, portfolio_totals, current_month, trailing_avg)
    return summary, snap_meta, manual


@router.get("/summary", response_model=FinancialIntelligenceSummary)
def get_summary(owner_id: str = Depends(require_user)) -> FinancialIntelligenceSummary:
    try:
        client = get_supabase_client()
    except SupabaseConfigurationError as exc:
        raise HTTPException(status_code=500, detail=f"Database configuration error: {exc}")

    summary, snap_meta, manual = _load_summary(client, owner_id)

    return FinancialIntelligenceSummary(
        currencies=summary["currencies"],
        portfolio_as_of=snap_meta["as_of"] if snap_meta else None,
        portfolio_partial=snap_meta["partial"] if snap_meta else None,
        manual_as_of=(manual.get("as_of") or manual.get("created_at")) if manual else None,
        has_manual_snapshot=manual is not None,
    )


# ---------------------------------------------------------------------------
# Financial goal progress v1 (Phase 22b-2)
# ---------------------------------------------------------------------------

_DEFAULT_METRIC = "net_worth"


class FinancialGoalProgress(BaseModel):
    id: str
    title: str
    target_value: float
    target_currency: str
    target_metric: str
    base_value: float | None        # the chosen metric in target_currency, or None if unavailable
    progress_pct: float | None      # base_value / target_value, or None if base unavailable
    status: str


class FinancialGoalsResponse(BaseModel):
    items: list[FinancialGoalProgress]
    portfolio_as_of: str | None = None
    portfolio_partial: bool | None = None


def _base_value(block: dict | None, metric: str) -> float | None:
    """Pull the chosen deterministic base from a per-currency summary block."""
    if block is None:
        return None
    if metric == "net_worth":
        return block.get("net_worth", {}).get("value")
    return block.get(metric)  # liquid_cash | invested | broker_total


@router.get("/financial-goals", response_model=FinancialGoalsResponse)
def get_financial_goals(owner_id: str = Depends(require_user)) -> FinancialGoalsResponse:
    try:
        client = get_supabase_client()
    except SupabaseConfigurationError as exc:
        raise HTTPException(status_code=500, detail=f"Database configuration error: {exc}")

    summary, snap_meta, _ = _load_summary(client, owner_id)
    blocks = {b["currency"]: b for b in summary["currencies"]}

    try:
        goals_res = (
            client.table("goals")
            .select("id,title,status,target_value,target_currency,target_metric")
            .eq("owner_id", owner_id)
            .not_.is_("target_value", "null")
            .not_.is_("target_currency", "null")
            .order("created_at", desc=True)
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database query failed") from exc

    items: list[FinancialGoalProgress] = []
    for g in goals_res.data or []:
        ccy = str(g["target_currency"]).strip().upper()
        metric = g.get("target_metric") or _DEFAULT_METRIC
        target = float(g["target_value"])
        base = _base_value(blocks.get(ccy), metric)
        progress = (base / target) if base is not None and target > 0 else None
        items.append(
            FinancialGoalProgress(
                id=g["id"],
                title=g["title"],
                target_value=target,
                target_currency=ccy,
                target_metric=metric,
                base_value=base,
                progress_pct=round(progress, 4) if progress is not None else None,
                status=g["status"],
            )
        )

    return FinancialGoalsResponse(
        items=items,
        portfolio_as_of=snap_meta["as_of"] if snap_meta else None,
        portfolio_partial=snap_meta["partial"] if snap_meta else None,
    )
