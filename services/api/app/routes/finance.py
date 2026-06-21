"""
Finance domain module (Phase 9) — read only.

Confirmed expenses are created by the atomic confirm_finance_item RPC (see review.py and
supabase/migrations/0003_money_events.sql). This router only reads money_events and computes
simple totals. There is no finance editing, completion, or deletion in Phase 9.

Multi-currency safety: totals are grouped by currency, then category — amounts in different
currencies are never added together.
"""
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.db.supabase_client import SupabaseConfigurationError, get_supabase_client
from app.security import require_dev_admin_token

router = APIRouter(tags=["finance"])

UNCATEGORIZED = "uncategorized"
CENTS = Decimal("0.01")


class MoneyEventResponse(BaseModel):
    id: str
    inbox_item_id: str
    amount: float
    currency: str
    direction: str
    merchant: Optional[str] = None
    category: Optional[str] = None
    occurred_at: Optional[str] = None
    notes: Optional[str] = None
    created_at: str


class CategoryTotal(BaseModel):
    category: str
    amount: float


class CurrencyTotals(BaseModel):
    currency: str
    total: float
    by_category: list[CategoryTotal]


class MoneyEventsListResponse(BaseModel):
    items: list[MoneyEventResponse]
    total: int
    totals_by_currency: list[CurrencyTotals]


def _compute_totals(items: list[MoneyEventResponse]) -> list[CurrencyTotals]:
    """
    Group expense amounts by currency, then category. Amounts in different currencies are
    never combined — each currency is its own bucket. Null category folds to 'uncategorized'.

    Money is summed with Decimal (built from each amount's string form, never from the binary
    float) so that e.g. 0.10 + 0.20 == 0.30 exactly. Income rows, if any reach here, are
    excluded defensively (the query also filters direction='expense' at the database).
    """
    buckets: dict[str, dict[str, Decimal]] = {}
    for event in items:
        if event.direction != "expense":
            continue
        by_category = buckets.setdefault(event.currency, {})
        category = event.category or UNCATEGORIZED
        amount = Decimal(str(event.amount))
        by_category[category] = by_category.get(category, Decimal("0")) + amount

    totals: list[CurrencyTotals] = []
    for currency in sorted(buckets):
        by_category = buckets[currency]
        currency_total = sum(by_category.values(), Decimal("0")).quantize(CENTS)
        totals.append(
            CurrencyTotals(
                currency=currency,
                total=float(currency_total),
                by_category=[
                    CategoryTotal(category=category, amount=float(amount.quantize(CENTS)))
                    for category, amount in sorted(by_category.items())
                ],
            )
        )
    return totals


@router.get("/money_events", dependencies=[Depends(require_dev_admin_token)])
def list_money_events() -> MoneyEventsListResponse:
    try:
        client = get_supabase_client()
    except SupabaseConfigurationError as exc:
        raise HTTPException(status_code=500, detail=f"Database configuration error: {exc}")

    try:
        result = (
            client.table("money_events")
            .select("*")
            .eq("direction", "expense")  # Phase 9 surfaces expenses only; exclude income at the DB
            .order("created_at", desc=True)
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database query failed") from exc

    items = [MoneyEventResponse(**row) for row in result.data]
    return MoneyEventsListResponse(
        items=items,
        total=len(items),
        totals_by_currency=_compute_totals(items),
    )
