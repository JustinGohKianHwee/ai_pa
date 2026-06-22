"""Protected creation and read APIs for normalized daily portfolio snapshots."""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.db.supabase_client import get_supabase_client
from app.security import require_user
from app.services.portfolio_snapshot import create_today_snapshot

router = APIRouter(prefix="/portfolio/snapshots", tags=["portfolio_snapshots"])


class SnapshotCurrencyTotal(BaseModel):
    currency: str
    market_value: float
    cash_value: float
    invested_value: float
    total_value: float
    market_value_complete: bool
    market_value_missing: int


class SnapshotSummary(BaseModel):
    snapshot_date: date
    partial_failure: bool
    currency_totals: list[SnapshotCurrencyTotal]


class SnapshotListResponse(BaseModel):
    items: list[SnapshotSummary]
    total: int


class SnapshotPosition(BaseModel):
    broker: str
    account_ref: str
    stable_asset_id: str
    asset_symbol: str
    asset_name: Optional[str] = None
    asset_type: str
    instrument_id: Optional[str] = None
    quantity: Optional[float] = None
    price: Optional[float] = None
    market_value: Optional[float] = None
    average_cost: Optional[float] = None
    cost_basis: Optional[float] = None
    unrealized_pnl: Optional[float] = None
    today_pnl: Optional[float] = None
    currency: str
    allocation_pct: Optional[float] = None
    quote_status: Optional[str] = None
    metadata_json: dict


class SnapshotDetail(BaseModel):
    snapshot_date: date
    generated_at: str
    source: str
    partial_failure: bool
    broker_status_json: dict
    currency_totals: list[SnapshotCurrencyTotal]
    positions: list[SnapshotPosition]


class HistoryPoint(BaseModel):
    snapshot_date: date
    total_value: float


@router.post("", dependencies=[Depends(require_user)])
async def create_snapshot() -> dict:
    try:
        return await create_today_snapshot()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Portfolio snapshot creation failed",
        ) from exc


@router.get("", response_model=SnapshotListResponse)
def list_snapshots(owner_id: str = Depends(require_user)) -> SnapshotListResponse:
    try:
        response = (
            get_supabase_client()
            .table("portfolio_snapshots")
            .select(
                "snapshot_date,partial_failure,"
                "portfolio_snapshot_currency_totals("
                "currency,market_value,cash_value,invested_value,total_value,"
                "market_value_complete,market_value_missing)"
            )
            .eq("owner_id", owner_id)
            .order("snapshot_date", desc=True)
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Could not load portfolio snapshots") from exc

    items = [
        SnapshotSummary(
            snapshot_date=row["snapshot_date"],
            partial_failure=row["partial_failure"],
            currency_totals=sorted(
                row.get("portfolio_snapshot_currency_totals") or [],
                key=lambda total: total["currency"],
            ),
        )
        for row in (response.data or [])
    ]
    return SnapshotListResponse(items=items, total=len(items))


@router.get("/history", response_model=list[HistoryPoint])
def snapshot_history(
    currency: str = Query(min_length=1),
    owner_id: str = Depends(require_user),
) -> list[HistoryPoint]:
    try:
        response = (
            get_supabase_client()
            .table("portfolio_snapshot_currency_totals")
            .select("total_value,portfolio_snapshots!inner(snapshot_date)")
            .eq("owner_id", owner_id)
            .eq("currency", currency.upper())
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Could not load portfolio history") from exc

    points = [
        HistoryPoint(
            snapshot_date=row["portfolio_snapshots"]["snapshot_date"],
            total_value=row["total_value"],
        )
        for row in (response.data or [])
    ]
    return sorted(points, key=lambda point: point.snapshot_date)


@router.get("/{snapshot_date}", response_model=SnapshotDetail)
def get_snapshot(
    snapshot_date: date,
    owner_id: str = Depends(require_user),
) -> SnapshotDetail:
    try:
        client = get_supabase_client()
        header_response = (
            client.table("portfolio_snapshots")
            .select("id,snapshot_date,generated_at,source,partial_failure,broker_status_json")
            .eq("owner_id", owner_id)
            .eq("snapshot_date", snapshot_date.isoformat())
            .limit(1)
            .execute()
        )
        headers = header_response.data or []
        if not headers:
            raise HTTPException(status_code=404, detail="Portfolio snapshot not found")

        header = headers[0]
        totals_response = (
            client.table("portfolio_snapshot_currency_totals")
            .select(
                "currency,market_value,cash_value,invested_value,total_value,"
                "market_value_complete,market_value_missing"
            )
            .eq("owner_id", owner_id)
            .eq("snapshot_id", header["id"])
            .order("currency")
            .execute()
        )
        positions_response = (
            client.table("portfolio_snapshot_positions")
            .select(
                "broker,account_ref,stable_asset_id,asset_symbol,asset_name,asset_type,"
                "instrument_id,quantity,price,market_value,average_cost,cost_basis,"
                "unrealized_pnl,today_pnl,currency,allocation_pct,quote_status,metadata_json"
            )
            .eq("owner_id", owner_id)
            .eq("snapshot_id", header["id"])
            .order("currency")
            .order("asset_symbol")
            .execute()
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Could not load portfolio snapshot") from exc

    return SnapshotDetail(
        snapshot_date=header["snapshot_date"],
        generated_at=header["generated_at"],
        source=header["source"],
        partial_failure=header["partial_failure"],
        broker_status_json=header["broker_status_json"],
        currency_totals=totals_response.data or [],
        positions=positions_response.data or [],
    )
