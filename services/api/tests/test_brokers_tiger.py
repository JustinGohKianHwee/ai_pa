"""
Tiger adapter tests — mock the SDK via a fake TradeClient; no network, no creds, never
imports tigeropen.

Covers exact allowlisted SDK methods, normalization (positions, per-currency cash, summary),
broker-reported today's P&L, fractional-share quantities, props-path config, get_assets
fallback, malformed/auth/timeout mapping, not-configured, account masking, and that order
methods are never accessed.
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


def _position(symbol="AAPL", currency="USD", mv=1700.0, upnl=200.0, price=170.0, today_pnl=None):
    return SimpleNamespace(
        contract=SimpleNamespace(
            symbol=symbol, sec_type="STK", currency=currency, identifier=symbol
        ),
        quantity=10,
        average_cost=150.0,
        market_value=mv,
        unrealized_pnl=upnl,
        market_price=price,
        today_pnl=today_pnl,
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


def _patch_client(monkeypatch, fake, account="TG987654321"):
    # _build_client now returns (client, resolved_account).
    monkeypatch.setattr(TigerAdapter, "_build_client", lambda self, *a, **k: (fake, account))
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
# props-path configuration (tiger_openapi_config.properties)
# ---------------------------------------------------------------------------


def _creds_props(monkeypatch):
    """Configure via a props file only — no explicit id/account/key env vars."""
    monkeypatch.setenv("TIGER_PROPS_PATH", "/tmp/tiger_config")
    monkeypatch.delenv("TIGER_ID", raising=False)
    monkeypatch.delenv("TIGER_ACCOUNT", raising=False)
    monkeypatch.delenv("TIGER_PRIVATE_KEY_PATH", raising=False)
    monkeypatch.delenv("TIGER_ACCOUNT_LABEL", raising=False)


def test_tiger_props_path_alone_is_configured(monkeypatch):
    """TIGER_PROPS_PATH without the explicit trio is sufficient; account comes from config."""
    _creds_props(monkeypatch)
    fake = FakeTradeClient(positions=[_position()], prime=_prime(), analytics=None)
    # _build_client resolves the account from the loaded config.
    _patch_client(monkeypatch, fake, account="TG987654321")
    result = TigerAdapter().fetch_portfolio()
    assert result.status == BrokerStatus.OK
    # account resolved from config is masked, never leaked
    assert result.accounts[0].account_ref == "T***4321"
    blob = result.model_dump_json()
    assert "TG987654321" not in blob


def test_tiger_props_path_no_account_returns_not_configured(monkeypatch):
    """A props file that yields no account cannot scope SDK calls."""
    _creds_props(monkeypatch)
    fake = FakeTradeClient(positions=[_position()], prime=_prime(), analytics=None)
    _patch_client(monkeypatch, fake, account=None)
    result = TigerAdapter().fetch_portfolio()
    assert result.status == BrokerStatus.NOT_CONFIGURED
    assert result.error == "account unavailable"


def test_tiger_build_client_loads_props_path(monkeypatch):
    """_build_client must hand props_path to the SDK and resolve the account from config."""
    import sys
    import types

    captured: dict = {}

    class FakeConfig:
        def __init__(self, props_path=None, **kwargs):
            captured["props_path"] = props_path
            self.account = "TGfromprops"

    class FakeTradeClient2:
        def __init__(self, config):
            captured["config"] = config

    def _mod(name):
        return types.ModuleType(name)

    config_mod = _mod("tigeropen.tiger_open_config")
    config_mod.TigerOpenClientConfig = FakeConfig
    trade_mod = _mod("tigeropen.trade.trade_client")
    trade_mod.TradeClient = FakeTradeClient2

    for name, mod in {
        "tigeropen": _mod("tigeropen"),
        "tigeropen.tiger_open_config": config_mod,
        "tigeropen.trade": _mod("tigeropen.trade"),
        "tigeropen.trade.trade_client": trade_mod,
    }.items():
        monkeypatch.setitem(sys.modules, name, mod)

    client, account = TigerAdapter()._build_client("/some/dir", None, None, None)
    assert captured["props_path"] == "/some/dir"
    assert account == "TGfromprops"


# ---------------------------------------------------------------------------
# happy path
# ---------------------------------------------------------------------------


def test_tiger_happy_path_normalizes(monkeypatch):
    _creds(monkeypatch)
    fake = FakeTradeClient(
        positions=[_position(today_pnl=12.5)],
        prime=_prime(),
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
    # broker-reported per-position today's P&L
    assert pos.today_pnl == 12.5
    assert pos.today_pnl_source == PnlSource.BROKER

    # per-currency cash
    assert {c.currency for c in result.cash} == {"USD", "HKD"}

    # summary today's P&L = sum of per-position broker P&L
    acct = result.accounts[0]
    assert acct.net_liquidation == 100000.0
    assert acct.today_pnl == 12.5
    assert acct.today_pnl_source == PnlSource.BROKER


def test_tiger_exact_sdk_methods_invoked(monkeypatch):
    _creds(monkeypatch)
    fake = FakeTradeClient(positions=[_position()], prime=_prime())
    _patch_client(monkeypatch, fake)
    TigerAdapter().fetch_portfolio()
    assert "get_positions" in fake.calls
    assert "get_prime_assets" in fake.calls
    # analytics is no longer used; today P&L comes from positions
    assert "get_analytics_asset" not in fake.calls
    # only allowlisted read methods were called
    assert set(fake.calls) <= {"get_positions", "get_prime_assets", "get_assets"}


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


def test_tiger_today_pnl_unavailable_when_positions_lack_it(monkeypatch):
    # No position carries today_pnl -> account today P&L is unavailable, not invented.
    _creds(monkeypatch)
    fake = FakeTradeClient(positions=[_position(today_pnl=None)], prime=_prime())
    _patch_client(monkeypatch, fake)
    result = TigerAdapter().fetch_portfolio()
    assert result.status == BrokerStatus.OK
    assert result.accounts[0].today_pnl is None
    assert result.accounts[0].today_pnl_source == PnlSource.UNAVAILABLE


def test_tiger_account_today_pnl_sums_positions(monkeypatch):
    _creds(monkeypatch)
    fake = FakeTradeClient(
        positions=[_position(symbol="A", today_pnl=10.0), _position(symbol="B", today_pnl=-3.5)],
        prime=_prime(),
    )
    _patch_client(monkeypatch, fake)
    result = TigerAdapter().fetch_portfolio()
    assert result.status == BrokerStatus.OK
    assert result.accounts[0].today_pnl == pytest.approx(6.5)
    assert result.accounts[0].today_pnl_source == PnlSource.BROKER


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


def test_tiger_fractional_position_uses_position_qty(monkeypatch):
    """Fractional positions: prefer position_qty (true decimal) over the scaled quantity."""
    _creds(monkeypatch)
    frac = SimpleNamespace(
        contract=SimpleNamespace(symbol="VOO", sec_type="STK", currency="USD", identifier="VOO"),
        quantity=1964327,       # integer scaled by 10**position_scale
        position_scale=5,
        position_qty=19.64327,  # the true decimal quantity
        average_cost=555.67,
        market_value=13523.60,
        unrealized_pnl=2608.34,
        market_price=688.46,
    )
    fake = FakeTradeClient(positions=[frac], prime=_prime(), analytics=None)
    _patch_client(monkeypatch, fake)
    result = TigerAdapter().fetch_portfolio()
    assert result.status == BrokerStatus.OK
    assert result.positions[0].quantity == pytest.approx(19.64327)


def test_tiger_position_qty_descale_fallback(monkeypatch):
    """If position_qty is absent, descale quantity by position_scale."""
    _creds(monkeypatch)
    frac = SimpleNamespace(
        contract=SimpleNamespace(symbol="VT", sec_type="STK", currency="USD", identifier="VT"),
        quantity=3708331,
        position_scale=5,
        # no position_qty attribute
        average_cost=152.39,
        market_value=5846.55,
        unrealized_pnl=195.14,
        market_price=157.66,
    )
    fake = FakeTradeClient(positions=[frac], prime=_prime(), analytics=None)
    _patch_client(monkeypatch, fake)
    result = TigerAdapter().fetch_portfolio()
    assert result.status == BrokerStatus.OK
    assert result.positions[0].quantity == pytest.approx(37.08331)


def test_tiger_nan_and_infinity_in_position_become_none(monkeypatch):
    """NaN / ±infinity must be rejected so totals and JSON serialization stay valid."""
    _creds(monkeypatch)
    nan_pos = SimpleNamespace(
        contract=SimpleNamespace(
            symbol="TEST", sec_type="STK", currency="USD", identifier="TEST"
        ),
        quantity=float("nan"),
        average_cost=float("inf"),
        market_value=float("nan"),
        unrealized_pnl=float("-inf"),
        market_price=None,
    )
    fake = FakeTradeClient(positions=[nan_pos], prime=_prime(), analytics=None)
    _patch_client(monkeypatch, fake)
    result = TigerAdapter().fetch_portfolio()
    assert result.status == BrokerStatus.OK
    pos = result.positions[0]
    assert pos.quantity == 0.0       # nan -> None -> 0.0 via `or 0.0`
    assert pos.average_cost is None
    assert pos.market_value is None
    assert pos.unrealized_pnl is None


# ---------------------------------------------------------------------------
# SDK allowlist enforcement
# ---------------------------------------------------------------------------


def test_tiger_sdk_call_rejects_non_allowlisted_method():
    """_sdk_call must raise before touching the client for any method not in the allowlist."""
    from app.brokers.tiger import _sdk_call

    sentinel = object()  # would explode on any attribute access — proves client is untouched
    with pytest.raises(ValueError, match="not permitted"):
        _sdk_call(sentinel, "place_order", account="TG123")
    with pytest.raises(ValueError, match="not permitted"):
        _sdk_call(sentinel, "cancel_order", account="TG123")
