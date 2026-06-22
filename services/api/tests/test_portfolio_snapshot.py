from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.brokers.models import (
    BrokerResult,
    BrokerStatus,
    CashBalance,
    PortfolioResponse,
    Position,
    QuoteStatus,
)
from app.services.portfolio_snapshot import create_today_snapshot, normalize_snapshot

OWNER_ID = "00000000-0000-0000-0000-000000000001"
SNAPSHOT_DATE = date(2026, 6, 22)


def _portfolio(*, missing_value: bool = False) -> PortfolioResponse:
    ok = BrokerResult(
        broker="ibkr",
        status=BrokerStatus.OK,
        positions=[
            Position(
                broker="ibkr",
                account_ref="U***4567",
                instrument_id="265598",
                symbol="AAPL",
                asset_class="stock",
                quantity=2,
                average_cost=100,
                currency="USD",
                market_price=150,
                market_value=300,
                unrealized_pnl=100,
                quote_status=QuoteStatus.LIVE,
            ),
            Position(
                broker="ibkr",
                account_ref="U***4567",
                symbol="MISSING",
                quantity=1,
                currency="USD",
                market_value=None if missing_value else 100,
            ),
            Position(
                broker="ibkr",
                account_ref="U***4567",
                symbol="HK",
                asset_class="stock",
                quantity=10,
                currency="HKD",
                market_value=800,
            ),
        ],
        cash=[
            CashBalance(
                broker="ibkr",
                account_ref="U***4567",
                currency="USD",
                amount=100,
            ),
            CashBalance(
                broker="ibkr",
                account_ref="U***4567",
                currency="HKD",
                amount=200,
            ),
        ],
    )
    failed = BrokerResult(
        broker="tiger",
        status=BrokerStatus.TIMEOUT,
        positions=[
            Position(
                broker="tiger",
                account_ref="T***0001",
                symbol="IGNORED",
                quantity=1,
                currency="USD",
                market_value=999,
            )
        ],
    )
    return PortfolioResponse(
        brokers=[ok, failed],
        totals_by_currency=[],
        generated_at="2026-06-22T12:00:00+00:00",
        partial_failure=True,
    )


def test_normalize_snapshot_is_deterministic_and_complete():
    portfolio = _portfolio()
    first = normalize_snapshot(portfolio, OWNER_ID, SNAPSHOT_DATE)
    second = normalize_snapshot(portfolio, OWNER_ID, SNAPSHOT_DATE)
    assert first == second

    header, totals, positions = first
    assert header == {
        "owner_id": OWNER_ID,
        "snapshot_date": "2026-06-22",
        "generated_at": "2026-06-22T12:00:00+00:00",
        "source": "manual",
        "partial_failure": True,
        "broker_status_json": {"ibkr": "ok", "tiger": "timeout"},
    }
    assert len(positions) == 5
    assert all(row["broker"] == "ibkr" for row in positions)

    by_currency = {row["currency"]: row for row in totals}
    assert by_currency["USD"] == {
        "currency": "USD",
        "market_value": 400.0,
        "cash_value": 100.0,
        "invested_value": 400.0,
        "total_value": 500.0,
        "market_value_complete": True,
        "market_value_missing": 0,
    }
    assert by_currency["HKD"]["total_value"] == 1000.0

    aapl = next(row for row in positions if row["asset_symbol"] == "AAPL")
    assert aapl["stable_asset_id"] == "265598"
    assert aapl["cost_basis"] == 200
    assert "broker_as_of" in aapl["metadata_json"]
    fallback = next(row for row in positions if row["asset_symbol"] == "MISSING")
    assert fallback["stable_asset_id"] == "ibkr:MISSING:USD"
    assert fallback["asset_type"] == "unknown"
    cash = next(row for row in positions if row["asset_type"] == "cash" and row["currency"] == "USD")
    assert cash["quantity"] == 100
    assert cash["price"] == 1.0
    assert cash["market_value"] == 100


def test_allocation_sums_to_about_100_per_currency():
    _, _, positions = normalize_snapshot(_portfolio(), OWNER_ID, SNAPSHOT_DATE)
    for currency in {row["currency"] for row in positions}:
        allocation = sum(
            row["allocation_pct"]
            for row in positions
            if row["currency"] == currency and row["allocation_pct"] is not None
        )
        assert allocation == pytest.approx(100, abs=0.02)


def test_missing_market_value_is_null_and_marks_total_incomplete():
    _, totals, positions = normalize_snapshot(
        _portfolio(missing_value=True), OWNER_ID, SNAPSHOT_DATE
    )
    usd = next(row for row in totals if row["currency"] == "USD")
    assert usd["market_value_complete"] is False
    assert usd["market_value_missing"] == 1
    missing = next(row for row in positions if row["asset_symbol"] == "MISSING")
    assert missing["market_value"] is None
    assert missing["allocation_pct"] is None
    assert missing["cost_basis"] is None


@pytest.mark.asyncio
async def test_create_today_snapshot_reuses_atomic_rpc_for_same_day(monkeypatch):
    portfolio = _portfolio()
    monkeypatch.setenv("OWNER_USER_ID", OWNER_ID)
    monkeypatch.setattr(
        "app.services.portfolio_snapshot.fetch_portfolio",
        AsyncMock(return_value=portfolio),
    )
    monkeypatch.setattr(
        "app.services.portfolio_snapshot._today_in_user_timezone",
        lambda: SNAPSHOT_DATE,
    )
    client = MagicMock()
    client.rpc.return_value.execute.return_value.data = "snapshot-id"
    monkeypatch.setattr(
        "app.services.portfolio_snapshot.get_supabase_client",
        lambda: client,
    )

    first = await create_today_snapshot()
    second = await create_today_snapshot()

    assert first == second
    assert first["snapshot_date"] == "2026-06-22"
    assert first["position_count"] == 5
    assert client.rpc.call_count == 2
    first_call = client.rpc.call_args_list[0]
    second_call = client.rpc.call_args_list[1]
    assert first_call == second_call
    assert first_call.args[0] == "create_portfolio_snapshot"
    assert first_call.args[1]["p_snapshot_date"] == "2026-06-22"
    assert first_call.args[1]["p_source"] == "manual"
