"""Normalize and persist one observational portfolio snapshot per owner per day."""

import os
from datetime import date, datetime

from fastapi import HTTPException

from app.brokers.models import BrokerStatus, PortfolioResponse
from app.brokers.portfolio_service import fetch_portfolio
from app.db.supabase_client import get_supabase_client
from app.routes.daily_review import _resolve_timezone


def _today_in_user_timezone() -> date:
    user_tz, _ = _resolve_timezone()
    return datetime.now(user_tz).date()


def normalize_snapshot(
    portfolio: PortfolioResponse,
    owner_id: str,
    snapshot_date: date,
) -> tuple[dict, list[dict], list[dict]]:
    """Convert the broker-neutral live portfolio into deterministic relational rows."""
    header = {
        "owner_id": owner_id,
        "snapshot_date": snapshot_date.isoformat(),
        "generated_at": portfolio.generated_at,
        "source": "manual",
        "partial_failure": portfolio.partial_failure,
        "broker_status_json": {
            broker.broker: broker.status.value for broker in portfolio.brokers
        },
    }

    positions: list[dict] = []
    totals: dict[str, dict] = {}

    def total_for(currency: str) -> dict:
        return totals.setdefault(
            currency,
            {
                "currency": currency,
                "market_value": 0.0,
                "cash_value": 0.0,
                "invested_value": 0.0,
                "total_value": 0.0,
                "market_value_complete": True,
                "market_value_missing": 0,
            },
        )

    for broker in portfolio.brokers:
        if broker.status != BrokerStatus.OK:
            continue

        for position in broker.positions:
            total = total_for(position.currency)
            if position.market_value is None:
                total["market_value_complete"] = False
                total["market_value_missing"] += 1
            else:
                total["market_value"] += position.market_value
                total["invested_value"] += position.market_value
                total["total_value"] += position.market_value

            stable_id = position.instrument_id or (
                f"{position.broker}:{position.symbol}:{position.currency}"
            )
            cost_basis = (
                position.average_cost * position.quantity
                if position.average_cost is not None
                else None
            )
            positions.append(
                {
                    "broker": position.broker,
                    "account_ref": position.account_ref,
                    "stable_asset_id": stable_id,
                    "asset_symbol": position.symbol,
                    "asset_name": None,
                    "asset_type": position.asset_class or "unknown",
                    "instrument_id": position.instrument_id,
                    "quantity": position.quantity,
                    "price": position.market_price,
                    "market_value": position.market_value,
                    "average_cost": position.average_cost,
                    "cost_basis": cost_basis,
                    "unrealized_pnl": position.unrealized_pnl,
                    "today_pnl": position.today_pnl,
                    "currency": position.currency,
                    "allocation_pct": None,
                    "quote_status": position.quote_status.value,
                    "metadata_json": {
                        "today_pnl_source": position.today_pnl_source.value,
                        "position_as_of": position.as_of,
                        "broker_as_of": broker.as_of,
                    },
                }
            )

        for cash in broker.cash:
            total = total_for(cash.currency)
            total["cash_value"] += cash.amount
            total["total_value"] += cash.amount
            positions.append(
                {
                    "broker": cash.broker,
                    "account_ref": cash.account_ref,
                    "stable_asset_id": f"{cash.broker}:{cash.currency}:{cash.currency}",
                    "asset_symbol": cash.currency,
                    "asset_name": None,
                    "asset_type": "cash",
                    "instrument_id": None,
                    "quantity": cash.amount,
                    "price": 1.0,
                    "market_value": cash.amount,
                    "average_cost": None,
                    "cost_basis": None,
                    "unrealized_pnl": None,
                    "today_pnl": None,
                    "currency": cash.currency,
                    "allocation_pct": None,
                    "quote_status": None,
                    "metadata_json": {"broker_as_of": broker.as_of},
                }
            )

    currency_totals = [totals[currency] for currency in sorted(totals)]
    total_by_currency = {row["currency"]: row["total_value"] for row in currency_totals}
    for position in positions:
        total_value = total_by_currency[position["currency"]]
        market_value = position["market_value"]
        if market_value is not None and total_value != 0:
            position["allocation_pct"] = round(market_value / total_value * 100, 2)

    positions.sort(
        key=lambda row: (
            row["currency"],
            row["broker"],
            row["account_ref"],
            row["asset_type"],
            row["stable_asset_id"],
        )
    )
    return header, currency_totals, positions


async def create_today_snapshot() -> dict:
    owner_id = os.getenv("OWNER_USER_ID")
    if not owner_id:
        raise HTTPException(
            status_code=500,
            detail="Server misconfiguration: auth is not configured",
        )

    snapshot_date = _today_in_user_timezone()
    portfolio = await fetch_portfolio()
    header, currency_totals, positions = normalize_snapshot(
        portfolio,
        owner_id,
        snapshot_date,
    )
    params = {
        "p_owner_id": owner_id,
        "p_snapshot_date": header["snapshot_date"],
        "p_generated_at": header["generated_at"],
        "p_source": header["source"],
        "p_partial_failure": header["partial_failure"],
        "p_broker_status": header["broker_status_json"],
        "p_currency_totals": currency_totals,
        "p_positions": positions,
    }
    get_supabase_client().rpc("create_portfolio_snapshot", params).execute()

    return {
        "snapshot_date": header["snapshot_date"],
        "currency_totals": currency_totals,
        "partial_failure": header["partial_failure"],
        "position_count": len(positions),
    }
