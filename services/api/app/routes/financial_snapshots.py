"""
Manual financial snapshots (Phase 22a) — read only.

Confirmed snapshots are created by confirm_financial_snapshot_item (see review.py and
supabase/migrations/0017_financial_snapshots.sql). This router only lists them; a snapshot is
immutable (update by capturing a new one), so there is no edit/delete endpoint.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.db.supabase_client import SupabaseConfigurationError, get_supabase_client
from app.security import require_user

router = APIRouter(tags=["financial_snapshots"])


class CurrencyAmountOut(BaseModel):
    currency: str
    amount: float


class FinancialSnapshotResponse(BaseModel):
    id: str
    inbox_item_id: str
    as_of: Optional[str] = None
    monthly_income: list[CurrencyAmountOut] = []
    monthly_investment: list[CurrencyAmountOut] = []
    liquid_cash: list[CurrencyAmountOut] = []
    liabilities: list[CurrencyAmountOut] = []
    notes: Optional[str] = None
    created_at: str


class FinancialSnapshotsListResponse(BaseModel):
    items: list[FinancialSnapshotResponse]
    total: int


def _row_to_response(row: dict) -> FinancialSnapshotResponse:
    return FinancialSnapshotResponse(
        id=row["id"],
        inbox_item_id=row["inbox_item_id"],
        as_of=row.get("as_of"),
        monthly_income=row.get("monthly_income_json") or [],
        monthly_investment=row.get("monthly_investment_json") or [],
        liquid_cash=row.get("liquid_cash_json") or [],
        liabilities=row.get("liabilities_json") or [],
        notes=row.get("notes"),
        created_at=row["created_at"],
    )


@router.get("/financial_snapshots")
def list_financial_snapshots(owner_id: str = Depends(require_user)) -> FinancialSnapshotsListResponse:
    try:
        client = get_supabase_client()
    except SupabaseConfigurationError as exc:
        raise HTTPException(status_code=500, detail=f"Database configuration error: {exc}")

    try:
        result = (
            client.table("manual_financial_snapshots")
            .select("*")
            .eq("owner_id", owner_id)
            .order("created_at", desc=True)
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database query failed") from exc

    items = [_row_to_response(row) for row in result.data]
    return FinancialSnapshotsListResponse(items=items, total=len(items))
