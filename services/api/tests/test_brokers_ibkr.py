"""
IBKR adapter tests — mock httpx.Client; no network, no creds.

Covers exact GET paths/methods, normalization, broker-reported daily P&L, malformed/auth/
gateway-down mapping, account masking, the GET-only allowlist (no order endpoint reachable),
and the strict TLS verification resolution.
"""
import httpx
import pytest

import app.brokers.ibkr as ibkr_mod
from app.brokers.ibkr import (
    IbkrAdapter,
    IbkrAllowlistError,
    IbkrConfigError,
    resolve_verify,
)
from app.brokers.models import BrokerStatus, PnlSource, QuoteStatus


# ---------------------------------------------------------------------------
# Fake httpx client
# ---------------------------------------------------------------------------


class FakeResp:
    def __init__(self, data=None, raise_exc=None):
        self._data = data
        self._raise = raise_exc

    def json(self):
        return self._data

    def raise_for_status(self):
        if self._raise is not None:
            raise self._raise


class FakeClient:
    def __init__(self, routes, requests):
        self.routes = routes
        self.requests = requests

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def request(self, method, path):
        self.requests.append((method, path))
        handler = self.routes.get(path)
        if handler is None:
            raise KeyError(path)
        if isinstance(handler, Exception):
            raise handler
        if isinstance(handler, FakeResp):
            return handler
        return FakeResp(handler)


def _http_status_error(code: int) -> httpx.HTTPStatusError:
    req = httpx.Request("GET", "https://localhost:5000/v1/api/x")
    resp = httpx.Response(code, request=req)
    return httpx.HTTPStatusError(f"{code}", request=req, response=resp)


def _patch_client(monkeypatch, routes):
    requests: list = []
    monkeypatch.setattr(ibkr_mod.httpx, "Client", lambda *a, **k: FakeClient(routes, requests))
    return requests


def _happy_routes():
    return {
        "/iserver/auth/status": {"authenticated": True},
        "/portfolio/accounts": [{"accountId": "U1234567"}],
        "/iserver/account/pnl/partitioned": {
            "upnl": {"U1234567.Core": {"dpl": 123.45, "upl": 50.0}}
        },
        "/portfolio/U1234567/summary": {
            "netliquidation": {"amount": 100000.0, "currency": "USD"},
            "unrealizedpnl": {"amount": 50.0},
        },
        "/portfolio/U1234567/positions/0": [
            {
                "conid": 265598,
                "contractDesc": "AAPL",
                "position": 10,
                "avgCost": 150.0,
                "mktPrice": 170.0,
                "mktValue": 1700.0,
                "currency": "USD",
                "assetClass": "STK",
                "unrealizedPnl": 200.0,
            }
        ],
        "/portfolio/U1234567/ledger": {
            "USD": {"cashbalance": 5000.0},
            "BASE": {"cashbalance": 99999.0},
        },
    }


def _enable(monkeypatch):
    monkeypatch.setenv("IBKR_ENABLED", "true")
    monkeypatch.setenv("IBKR_CPAPI_BASE_URL", "https://localhost:5000/v1/api")
    monkeypatch.delenv("IBKR_CPAPI_CACERT", raising=False)
    monkeypatch.delenv("IBKR_ACCOUNT_LABEL", raising=False)


# ---------------------------------------------------------------------------
# not configured
# ---------------------------------------------------------------------------


def test_ibkr_not_enabled_returns_not_configured(monkeypatch):
    monkeypatch.delenv("IBKR_ENABLED", raising=False)
    result = IbkrAdapter().fetch_portfolio()
    assert result.status == BrokerStatus.NOT_CONFIGURED


# ---------------------------------------------------------------------------
# happy path: normalization + exact paths + no order endpoint
# ---------------------------------------------------------------------------


def test_ibkr_happy_path_normalizes(monkeypatch):
    _enable(monkeypatch)
    _patch_client(monkeypatch, _happy_routes())
    result = IbkrAdapter().fetch_portfolio()

    assert result.status == BrokerStatus.OK
    assert len(result.positions) == 1
    pos = result.positions[0]
    assert pos.symbol == "AAPL"
    assert pos.instrument_id == "265598"
    assert pos.quantity == 10
    assert pos.market_value == 1700.0
    assert pos.currency == "USD"
    assert pos.quote_status == QuoteStatus.UNKNOWN
    assert pos.today_pnl_source == PnlSource.UNAVAILABLE  # CPAPI has no per-position daily P&L

    # account-level daily P&L is broker-reported
    assert len(result.accounts) == 1
    acct = result.accounts[0]
    assert acct.net_liquidation == 100000.0
    assert acct.today_pnl == 123.45
    assert acct.today_pnl_source == PnlSource.BROKER

    # cash: BASE pseudo-currency is skipped
    currencies = {c.currency for c in result.cash}
    assert currencies == {"USD"}


def test_ibkr_exact_paths_and_methods(monkeypatch):
    _enable(monkeypatch)
    requests = _patch_client(monkeypatch, _happy_routes())
    IbkrAdapter().fetch_portfolio()

    methods = {m for m, _ in requests}
    assert methods == {"GET"}
    paths = {p for _, p in requests}
    assert paths == {
        "/iserver/auth/status",
        "/portfolio/accounts",
        "/iserver/account/pnl/partitioned",
        "/portfolio/U1234567/summary",
        "/portfolio/U1234567/positions/0",
        "/portfolio/U1234567/ledger",
    }
    # No order/trade endpoint was ever requested.
    assert not any("order" in p.lower() for _, p in requests)


def test_ibkr_account_masked(monkeypatch):
    _enable(monkeypatch)
    _patch_client(monkeypatch, _happy_routes())
    result = IbkrAdapter().fetch_portfolio()
    blob = result.model_dump_json()
    assert "U1234567" not in blob  # full account number never leaks
    assert result.positions[0].account_ref == "U***4567"


def test_ibkr_account_label_overrides_mask(monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setenv("IBKR_ACCOUNT_LABEL", "Main IBKR")
    _patch_client(monkeypatch, _happy_routes())
    result = IbkrAdapter().fetch_portfolio()
    assert result.accounts[0].account_ref == "Main IBKR"


# ---------------------------------------------------------------------------
# error mapping
# ---------------------------------------------------------------------------


def test_ibkr_not_authenticated_returns_auth_error(monkeypatch):
    _enable(monkeypatch)
    routes = _happy_routes()
    routes["/iserver/auth/status"] = {"authenticated": False}
    _patch_client(monkeypatch, routes)
    result = IbkrAdapter().fetch_portfolio()
    assert result.status == BrokerStatus.AUTH_ERROR


def test_ibkr_http_401_returns_auth_error(monkeypatch):
    _enable(monkeypatch)
    routes = _happy_routes()
    routes["/iserver/auth/status"] = FakeResp(raise_exc=_http_status_error(401))
    _patch_client(monkeypatch, routes)
    result = IbkrAdapter().fetch_portfolio()
    assert result.status == BrokerStatus.AUTH_ERROR


def test_ibkr_gateway_down_returns_unavailable(monkeypatch):
    _enable(monkeypatch)
    routes = _happy_routes()
    routes["/iserver/auth/status"] = httpx.ConnectError("refused")
    _patch_client(monkeypatch, routes)
    result = IbkrAdapter().fetch_portfolio()
    assert result.status == BrokerStatus.UNAVAILABLE


def test_ibkr_malformed_accounts_returns_malformed(monkeypatch):
    _enable(monkeypatch)
    routes = _happy_routes()
    routes["/portfolio/accounts"] = {"not": "a list"}
    _patch_client(monkeypatch, routes)
    result = IbkrAdapter().fetch_portfolio()
    assert result.status == BrokerStatus.MALFORMED_RESPONSE


# ---------------------------------------------------------------------------
# GET-only allowlist
# ---------------------------------------------------------------------------


def test_ibkr_request_rejects_non_get_method():
    adapter = IbkrAdapter()
    requests: list = []
    client = FakeClient({}, requests)
    with pytest.raises(IbkrAllowlistError):
        adapter._request(client, "POST", "/iserver/account/U1234567/orders")
    assert requests == []  # rejected before any network call


def test_ibkr_request_rejects_non_allowlisted_path():
    adapter = IbkrAdapter()
    requests: list = []
    client = FakeClient({}, requests)
    with pytest.raises(IbkrAllowlistError):
        adapter._request(client, "GET", "/iserver/account/U1234567/orders")
    assert requests == []


def test_ibkr_request_allows_allowlisted_get():
    adapter = IbkrAdapter()
    requests: list = []
    client = FakeClient({"/portfolio/accounts": []}, requests)
    adapter._request(client, "GET", "/portfolio/accounts")
    assert requests == [("GET", "/portfolio/accounts")]


# ---------------------------------------------------------------------------
# TLS verification resolution
# ---------------------------------------------------------------------------


def test_tls_cacert_takes_precedence(monkeypatch):
    monkeypatch.setenv("IBKR_CPAPI_CACERT", "/path/to/ca.pem")
    assert resolve_verify("https://example.com/v1/api") == "/path/to/ca.pem"


def test_tls_loopback_allows_insecure(monkeypatch):
    monkeypatch.delenv("IBKR_CPAPI_CACERT", raising=False)
    assert resolve_verify("https://localhost:5000/v1/api") is False
    assert resolve_verify("https://127.0.0.1:5000/v1/api") is False


def test_tls_remote_without_cacert_raises(monkeypatch):
    monkeypatch.delenv("IBKR_CPAPI_CACERT", raising=False)
    with pytest.raises(IbkrConfigError):
        resolve_verify("https://broker.example.com/v1/api")


def test_ibkr_remote_without_cacert_returns_error_status(monkeypatch):
    monkeypatch.setenv("IBKR_ENABLED", "true")
    monkeypatch.setenv("IBKR_CPAPI_BASE_URL", "https://broker.example.com/v1/api")
    monkeypatch.delenv("IBKR_CPAPI_CACERT", raising=False)
    # Should never construct a client / hit the network.
    monkeypatch.setattr(
        ibkr_mod.httpx,
        "Client",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("client must not be built")),
    )
    result = IbkrAdapter().fetch_portfolio()
    assert result.status == BrokerStatus.ERROR
    assert result.error == "tls configuration error"
