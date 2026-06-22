"""
GET /portfolio orchestration tests — adapters mocked at the boundary.

Covers auth guard, the success/failure matrix, partial failure, totals grouped by currency
(never summed across currencies), per-metric completeness flags, the read-only/no-Supabase
invariants, no broker import at module import, and the thread-accumulation guard.
"""
import asyncio
import sys
import threading
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import app.brokers.portfolio_service as ps
from app.brokers.ibkr import IbkrAdapter
from app.brokers.models import BrokerResult, BrokerStatus, Position
from app.brokers.tiger import TigerAdapter
from app.main import app

client = TestClient(app)
VALID_TOKEN = "test-dev-admin-token-xyz"


def _auth_header(token: str = VALID_TOKEN) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def _clear_inflight():
    ps._INFLIGHT.clear()
    yield
    ps._INFLIGHT.clear()


def _pos(broker: str, ccy: str = "USD", mv=1000.0, upnl=10.0) -> Position:
    return Position(
        broker=broker,
        account_ref="U***4567",
        symbol="SYM",
        quantity=1,
        currency=ccy,
        market_value=mv,
        unrealized_pnl=upnl,
    )


def _ok(broker: str, positions=None) -> BrokerResult:
    return BrokerResult(broker=broker, status=BrokerStatus.OK, positions=positions or [])


def _fail(broker: str, status: BrokerStatus) -> BrokerResult:
    return BrokerResult(broker=broker, status=status, error="x")


def _patch(monkeypatch, ibkr_result: BrokerResult, tiger_result: BrokerResult):
    monkeypatch.setattr(IbkrAdapter, "fetch_portfolio", lambda self: ibkr_result)
    monkeypatch.setattr(TigerAdapter, "fetch_portfolio", lambda self: tiger_result)


def _broker(body: dict, name: str) -> dict:
    return next(b for b in body["brokers"] if b["broker"] == name)


# ---------------------------------------------------------------------------
# Auth guard
# ---------------------------------------------------------------------------


def test_portfolio_missing_token_returns_403(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    assert client.get("/portfolio").status_code == 403


def test_portfolio_wrong_token_returns_403(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    assert client.get("/portfolio", headers={"Authorization": "Bearer nope"}).status_code == 403


# ---------------------------------------------------------------------------
# Success / failure matrix
# ---------------------------------------------------------------------------


def test_portfolio_both_ok(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    _patch(monkeypatch, _ok("ibkr", [_pos("ibkr")]), _ok("tiger", [_pos("tiger")]))
    r = client.get("/portfolio", headers=_auth_header())
    assert r.status_code == 200
    body = r.json()
    assert body["partial_failure"] is False
    assert _broker(body, "ibkr")["status"] == "ok"
    assert _broker(body, "tiger")["status"] == "ok"


def test_portfolio_tiger_ok_ibkr_failed(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    _patch(monkeypatch, _fail("ibkr", BrokerStatus.TIMEOUT), _ok("tiger", [_pos("tiger")]))
    body = client.get("/portfolio", headers=_auth_header()).json()
    assert body["partial_failure"] is True
    assert _broker(body, "ibkr")["status"] == "timeout"
    assert _broker(body, "tiger")["status"] == "ok"
    # totals come only from the successful broker
    assert len(body["totals_by_currency"]) == 1


def test_portfolio_ibkr_ok_tiger_failed(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    _patch(monkeypatch, _ok("ibkr", [_pos("ibkr")]), _fail("tiger", BrokerStatus.AUTH_ERROR))
    body = client.get("/portfolio", headers=_auth_header()).json()
    assert body["partial_failure"] is True
    assert _broker(body, "ibkr")["status"] == "ok"
    assert _broker(body, "tiger")["status"] == "auth_error"


def test_portfolio_both_failed(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    _patch(monkeypatch, _fail("ibkr", BrokerStatus.UNAVAILABLE), _fail("tiger", BrokerStatus.ERROR))
    body = client.get("/portfolio", headers=_auth_header()).json()
    assert body["partial_failure"] is True
    assert body["totals_by_currency"] == []


def test_portfolio_empty(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    _patch(monkeypatch, _ok("ibkr"), _ok("tiger"))
    body = client.get("/portfolio", headers=_auth_header()).json()
    assert body["partial_failure"] is False
    assert body["totals_by_currency"] == []


def test_portfolio_multiple_accounts(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    ibkr = BrokerResult(
        broker="ibkr",
        status=BrokerStatus.OK,
        positions=[_pos("ibkr"), _pos("ibkr")],
    )
    _patch(monkeypatch, ibkr, _ok("tiger"))
    body = client.get("/portfolio", headers=_auth_header()).json()
    assert len(_broker(body, "ibkr")["positions"]) == 2


# ---------------------------------------------------------------------------
# Totals: grouped by currency, never summed, completeness per metric
# ---------------------------------------------------------------------------


def test_portfolio_totals_grouped_by_currency_never_summed(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    _patch(
        monkeypatch,
        _ok("ibkr", [_pos("ibkr", ccy="USD", mv=1000.0)]),
        _ok("tiger", [_pos("tiger", ccy="HKD", mv=2000.0)]),
    )
    totals = client.get("/portfolio", headers=_auth_header()).json()["totals_by_currency"]
    by_ccy = {t["currency"]: t for t in totals}
    assert set(by_ccy) == {"USD", "HKD"}
    assert by_ccy["USD"]["market_value"] == 1000.0
    assert by_ccy["HKD"]["market_value"] == 2000.0


def test_portfolio_same_currency_summed_across_brokers(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    _patch(
        monkeypatch,
        _ok("ibkr", [_pos("ibkr", ccy="USD", mv=1000.0)]),
        _ok("tiger", [_pos("tiger", ccy="USD", mv=500.0)]),
    )
    totals = client.get("/portfolio", headers=_auth_header()).json()["totals_by_currency"]
    assert len(totals) == 1
    assert totals[0]["currency"] == "USD"
    assert totals[0]["market_value"] == 1500.0
    assert totals[0]["market_value_complete"] is True


def test_portfolio_incomplete_totals_flagged_per_metric(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    # Two USD positions; one missing market_value but both have unrealized_pnl.
    ibkr = _ok(
        "ibkr",
        [
            _pos("ibkr", ccy="USD", mv=1000.0, upnl=10.0),
            _pos("ibkr", ccy="USD", mv=None, upnl=20.0),
        ],
    )
    _patch(monkeypatch, ibkr, _ok("tiger"))
    totals = client.get("/portfolio", headers=_auth_header()).json()["totals_by_currency"]
    usd = next(t for t in totals if t["currency"] == "USD")
    # market value is an incomplete subtotal
    assert usd["market_value"] == 1000.0
    assert usd["market_value_complete"] is False
    assert usd["market_value_missing"] == 1
    # unrealized P&L is complete and tracked separately
    assert usd["unrealized_pnl"] == 30.0
    assert usd["unrealized_pnl_complete"] is True
    assert usd["unrealized_pnl_missing"] == 0


# ---------------------------------------------------------------------------
# Read-only / isolation invariants
# ---------------------------------------------------------------------------


def test_no_broker_sdk_imported_at_module_import():
    # Importing the route/service must not import the Tiger SDK.
    assert "tigeropen" not in sys.modules


def test_health_works_without_broker_config(monkeypatch):
    monkeypatch.delenv("IBKR_ENABLED", raising=False)
    monkeypatch.delenv("TIGER_ID", raising=False)
    assert client.get("/health").status_code == 200


def test_portfolio_makes_no_supabase_calls(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    _patch(monkeypatch, _ok("ibkr", [_pos("ibkr")]), _ok("tiger"))
    sb = MagicMock()
    with patch("app.db.supabase_client.get_supabase_client", sb):
        client.get("/portfolio", headers=_auth_header())
    sb.assert_not_called()


def test_portfolio_no_full_account_number_in_response(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    _patch(monkeypatch, _ok("ibkr", [_pos("ibkr")]), _ok("tiger"))
    text = client.get("/portfolio", headers=_auth_header()).text
    assert "U***4567" in text  # masked ref present
    assert "private_key" not in text
    assert "Bearer" not in text


# ---------------------------------------------------------------------------
# Thread-accumulation guard
# ---------------------------------------------------------------------------


def test_repeated_timeout_no_thread_accumulation(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("PORTFOLIO_BROKER_TIMEOUT", "0.3")
    ps._INFLIGHT.clear()

    release = threading.Event()
    started = threading.Semaphore(0)
    ibkr_calls = {"n": 0}

    def slow(self):
        ibkr_calls["n"] += 1
        started.release()
        release.wait(timeout=5)
        return BrokerResult(broker="ibkr", status=BrokerStatus.OK)

    monkeypatch.setattr(IbkrAdapter, "fetch_portfolio", slow)
    monkeypatch.setattr(
        TigerAdapter,
        "fetch_portfolio",
        lambda self: BrokerResult(broker="tiger", status=BrokerStatus.OK),
    )

    async def run_two():
        t1 = asyncio.create_task(ps.fetch_portfolio())
        await asyncio.to_thread(started.acquire)  # wait until the ibkr thread has started
        t2 = asyncio.create_task(ps.fetch_portfolio())
        return await asyncio.gather(t1, t2)

    try:
        r1, r2 = asyncio.run(run_two())
    finally:
        release.set()

    def ibkr_of(resp):
        return next(b for b in resp.brokers if b.broker == "ibkr")

    # First request: ibkr times out (thread still running, but bounded).
    assert ibkr_of(r1).status == BrokerStatus.TIMEOUT
    # Second request while the first is still in flight: short-circuited, no new thread.
    assert ibkr_of(r2).status == BrokerStatus.UNAVAILABLE
    assert ibkr_of(r2).error == "busy"
    # Only one ibkr worker thread ever ran despite two requests.
    assert ibkr_calls["n"] == 1
