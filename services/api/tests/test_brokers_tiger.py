"""
Tiger adapter tests — mock the SDK via a fake TradeClient; no network, no creds, never
imports tigeropen.

Covers exact allowlisted SDK methods, normalization (positions, per-currency cash, summary),
calculated today's P&L, get_assets fallback, malformed/auth/timeout mapping, not-configured,
account masking, and that order methods are never accessed.
"""
from types import SimpleNamespace

import pytest

from app.brokers.models import BrokerStatus, PnlSource, QuoteStatus
from app.brokers.tiger import TigerAdapter


# ---------------------------------------------------------------------------
# Fake SDK client
# ---------------------------------------------------------------------------


class FakeTradeClient:
    """
    Records allowlisted read calls. Order methods are properties that raise the instant
    they are *accessed*, so any attempt to touch them fails the test.
    """

    def __init__(self, positions=None, prime=None, assets=None, analytics=None, raises=None):
        self._positions = positions
        self._prime = prime
        self._assets = assets
        self._analytics = analytics
        self._raises = raises or {}
        self.calls: list[str] = []

    def get_positions(self, account=None):
        self.calls.append("get_positions")
        if "get_positions" in self._raises:
            raise self._raises["get_positions"]
        return self._positions

    def get_prime_assets(self, account=None):
        self.calls.append("get_prime_assets")
        if "get_prime_assets" in self._raises:
            raise self._raises["get_prime_assets"]
        return self._prime

    def get_assets(self, account=None):
        self.calls.append("get_assets")
        if "get_assets" in self._raises:
            raise self._raises["get_assets"]
        return self._assets

    def get_analytics_asset(self, account=None):
        self.calls.append("get_analytics_asset")
        if "get_analytics_asset" in self._raises:
            raise self._raises["get_analytics_asset"]
        return self._analytics

    # --- forbidden order methods (must never be accessed) ---
    @property
    def place_order(self):
        raise RuntimeError("place_order must never be accessed")

    @property
    def modify_order(self):
        raise RuntimeError("modify_order must never be accessed")

    @property
    def cancel_order(self):
        raise RuntimeError("cancel_order must never be accessed")


def _position(symbol="AAPL", currency="USD", mv=1700.0, upnl=200.0, price=170.0):
    return SimpleNamespace(
        contract=SimpleNamespace(
            symbol=symbol, sec_type="STK", currency=currency, identifier=symbol
        ),
        quantity=10,
        average_cost=150.0,
        market_value=mv,
        unrealized_pnl=upnl,
        market_price=price,
    )


def _prime(currencies=("USD", "HKD")):
    currency_assets = {
        ccy: SimpleNamespace(cash_balance=5000.0, cash_available_for_trade=4000.0)
        for ccy in currencies
    }
    seg = SimpleNamespace(
        net_liquidation=100000.0,
        unrealized_pl=250.0,
        realized_pl=0.0,
        currency="USD",
        currency_assets=currency_assets,
    )
    return SimpleNamespace(segments={"S": seg})


def _creds(monkeypatch):
    monkeypatch.setenv("TIGER_ID", "tid-123")
    monkeypatch.setenv("TIGER_ACCOUNT", "TG987654321")
    monkeypatch.setenv("TIGER_PRIVATE_KEY_PATH", "/tmp/key.pem")
    monkeypatch.delenv("TIGER_ACCOUNT_LABEL", raising=False)


def _patch_client(monkeypatch, fake):
    monkeypatch.setattr(TigerAdapter, "_build_client", lambda self, *a, **k: fake)
    return fake


# ---------------------------------------------------------------------------
# not configured
# ---------------------------------------------------------------------------


def test_tiger_missing_creds_returns_not_configured(monkeypatch):
    monkeypatch.delenv("TIGER_ID", raising=False)
    monkeypatch.delenv("TIGER_ACCOUNT", raising=False)
    monkeypatch.delenv("TIGER_PRIVATE_KEY_PATH", raising=False)
    result = TigerAdapter().fetch_portfolio()
    assert result.status == BrokerStatus.NOT_CONFIGURED


def test_tiger_sdk_absent_returns_not_configured(monkeypatch):
    _creds(monkeypatch)

    def _raise_import(self, *a, **k):
        raise ImportError("no tigeropen")

    monkeypatch.setattr(TigerAdapter, "_build_client", _raise_import)
    result = TigerAdapter().fetch_portfolio()
    assert result.status == BrokerStatus.NOT_CONFIGURED


# ---------------------------------------------------------------------------
# happy path
# ---------------------------------------------------------------------------


def test_tiger_happy_path_normalizes(monkeypatch):
    _creds(monkeypatch)
    fake = FakeTradeClient(
        positions=[_position()],
        prime=_prime(),
        analytics=SimpleNamespace(pnl=321.0, pnl_percentage=0.5),
    )
    _patch_client(monkeypatch, fake)

    result = TigerAdapter().fetch_portfolio()
    assert result.status == BrokerStatus.OK

    assert len(result.positions) == 1
    pos = result.positions[0]
    assert pos.symbol == "AAPL"
    assert pos.currency == "USD"
    assert pos.market_value == 1700.0
    assert pos.quote_status == QuoteStatus.UNKNOWN
    assert pos.today_pnl_source == PnlSource.UNAVAILABLE  # no per-position daily P&L

    # per-currency cash
    assert {c.currency for c in result.cash} == {"USD", "HKD"}

    # summary + calculated today's P&L from analytics
    acct = result.accounts[0]
    assert acct.net_liquidation == 100000.0
    assert acct.today_pnl == 321.0
    assert acct.today_pnl_source == PnlSource.CALCULATED


def test_tiger_exact_sdk_methods_invoked(monkeypatch):
    _creds(monkeypatch)
    fake = FakeTradeClient(
        positions=[_position()], prime=_prime(), analytics=SimpleNamespace(pnl=1.0)
    )
    _patch_client(monkeypatch, fake)
    TigerAdapter().fetch_portfolio()
    assert "get_positions" in fake.calls
    assert "get_prime_assets" in fake.calls
    assert "get_analytics_asset" in fake.calls
    # only allowlisted read methods were called
    assert set(fake.calls) <= {
        "get_positions",
        "get_prime_assets",
        "get_assets",
        "get_analytics_asset",
    }


def test_tiger_order_methods_never_accessed(monkeypatch):
    """Happy path completes OK, which proves no forbidden order property was touched."""
    _creds(monkeypatch)
    fake = FakeTradeClient(
        positions=[_position()], prime=_prime(), analytics=SimpleNamespace(pnl=1.0)
    )
    _patch_client(monkeypatch, fake)
    result = TigerAdapter().fetch_portfolio()
    assert result.status == BrokerStatus.OK
    # sanity: touching an order property does raise
    with pytest.raises(RuntimeError):
        _ = fake.place_order


def test_tiger_account_masked(monkeypatch):
    _creds(monkeypatch)
    fake = FakeTradeClient(positions=[_position()], prime=_prime(), analytics=None)
    _patch_client(monkeypatch, fake)
    result = TigerAdapter().fetch_portfolio()
    blob = result.model_dump_json()
    assert "TG987654321" not in blob
    assert result.accounts[0].account_ref == "T***4321"


# ---------------------------------------------------------------------------
# analytics + fallback
# ---------------------------------------------------------------------------


def test_tiger_analytics_failure_tolerated(monkeypatch):
    _creds(monkeypatch)
    fake = FakeTradeClient(
        positions=[_position()],
        prime=_prime(),
        raises={"get_analytics_asset": Exception("analytics down")},
    )
    _patch_client(monkeypatch, fake)
    result = TigerAdapter().fetch_portfolio()
    assert result.status == BrokerStatus.OK
    assert result.accounts[0].today_pnl is None
    assert result.accounts[0].today_pnl_source == PnlSource.UNAVAILABLE


def test_tiger_get_assets_fallback(monkeypatch):
    _creds(monkeypatch)
    assets_obj = SimpleNamespace(
        summary=SimpleNamespace(net_liquidation=42000.0, currency="USD", unrealized_pnl=10.0),
        currency_assets={"USD": SimpleNamespace(cash_balance=2000.0)},
    )
    fake = FakeTradeClient(
        positions=[_position()],
        assets=assets_obj,
        raises={"get_prime_assets": Exception("not a prime account")},
        analytics=SimpleNamespace(pnl=5.0),
    )
    _patch_client(monkeypatch, fake)
    result = TigerAdapter().fetch_portfolio()
    assert result.status == BrokerStatus.OK
    assert "get_assets" in fake.calls
    assert result.accounts[0].net_liquidation == 42000.0
    assert {c.currency for c in result.cash} == {"USD"}


# ---------------------------------------------------------------------------
# error mapping
# ---------------------------------------------------------------------------


def test_tiger_auth_failure_returns_auth_error(monkeypatch):
    _creds(monkeypatch)
    fake = FakeTradeClient(raises={"get_positions": Exception("auth token invalid")})
    _patch_client(monkeypatch, fake)
    result = TigerAdapter().fetch_portfolio()
    assert result.status == BrokerStatus.AUTH_ERROR


def test_tiger_timeout_returns_timeout(monkeypatch):
    _creds(monkeypatch)
    fake = FakeTradeClient(raises={"get_positions": TimeoutError("timed out")})
    _patch_client(monkeypatch, fake)
    result = TigerAdapter().fetch_portfolio()
    assert result.status == BrokerStatus.TIMEOUT


def test_tiger_malformed_positions_returns_malformed(monkeypatch):
    _creds(monkeypatch)
    # get_positions returns a non-iterable truthy value -> TypeError during normalize
    fake = FakeTradeClient(positions=5, prime=_prime(), analytics=None)
    _patch_client(monkeypatch, fake)
    result = TigerAdapter().fetch_portfolio()
    assert result.status == BrokerStatus.MALFORMED_RESPONSE


def test_tiger_nullable_price_pnl_tolerated(monkeypatch):
    _creds(monkeypatch)
    fake = FakeTradeClient(
        positions=[_position(mv=None, upnl=None, price=None)], prime=_prime(), analytics=None
    )
    _patch_client(monkeypatch, fake)
    result = TigerAdapter().fetch_portfolio()
    assert result.status == BrokerStatus.OK
    pos = result.positions[0]
    assert pos.market_value is None
    assert pos.unrealized_pnl is None
    assert pos.quote_status == QuoteStatus.UNAVAILABLE
