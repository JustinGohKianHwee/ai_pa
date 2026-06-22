from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import mint_test_token

client = TestClient(app)
VALID_TOKEN = mint_test_token()
OWNER_ID = "00000000-0000-0000-0000-000000000001"


def _auth_header(token: str = VALID_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class Query:
    def __init__(self, data):
        self.data = data
        self.calls: list[tuple] = []

    def select(self, *args, **kwargs):
        self.calls.append(("select", args, kwargs))
        return self

    def eq(self, *args, **kwargs):
        self.calls.append(("eq", args, kwargs))
        return self

    def order(self, *args, **kwargs):
        self.calls.append(("order", args, kwargs))
        return self

    def limit(self, *args, **kwargs):
        self.calls.append(("limit", args, kwargs))
        return self

    def execute(self):
        return SimpleNamespace(data=self.data)


class FakeSupabase:
    def __init__(self, tables: dict[str, list]):
        self.queries = {name: Query(data) for name, data in tables.items()}

    def table(self, name: str):
        return self.queries[name]


AUTH_CASES = [
    ("post", "/portfolio/snapshots"),
    ("get", "/portfolio/snapshots"),
    ("get", "/portfolio/snapshots/history?currency=USD"),
    ("get", "/portfolio/snapshots/2026-06-22"),
]


@pytest.mark.parametrize(("method", "path"), AUTH_CASES)
def test_snapshot_routes_reject_missing_token(method, path):
    assert client.request(method, path).status_code == 401


@pytest.mark.parametrize(("method", "path"), AUTH_CASES)
def test_snapshot_routes_reject_non_owner_token(method, path):
    token = mint_test_token(sub="different-user")
    response = client.request(method, path, headers=_auth_header(token))
    assert response.status_code == 403


def test_create_snapshot_returns_service_summary(monkeypatch):
    summary = {
        "snapshot_date": "2026-06-22",
        "currency_totals": [],
        "partial_failure": False,
        "position_count": 0,
    }
    monkeypatch.setattr(
        "app.routes.portfolio_snapshots.create_today_snapshot",
        AsyncMock(return_value=summary),
    )
    response = client.post("/portfolio/snapshots", headers=_auth_header())
    assert response.status_code == 200
    assert response.json() == summary


def test_list_snapshots_filters_owner_and_shapes_response(monkeypatch):
    fake = FakeSupabase(
        {
            "portfolio_snapshots": [
                {
                    "snapshot_date": "2026-06-22",
                    "partial_failure": False,
                    "portfolio_snapshot_currency_totals": [
                        {
                            "currency": "USD",
                            "market_value": 100,
                            "cash_value": 20,
                            "invested_value": 100,
                            "total_value": 120,
                            "market_value_complete": True,
                            "market_value_missing": 0,
                        }
                    ],
                }
            ]
        }
    )
    monkeypatch.setattr(
        "app.routes.portfolio_snapshots.get_supabase_client", lambda: fake
    )
    response = client.get("/portfolio/snapshots", headers=_auth_header())
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["currency_totals"][0]["total_value"] == 120
    assert ("eq", ("owner_id", OWNER_ID), {}) in fake.queries["portfolio_snapshots"].calls


def test_history_filters_owner_and_currency(monkeypatch):
    fake = FakeSupabase(
        {
            "portfolio_snapshot_currency_totals": [
                {
                    "total_value": 120,
                    "portfolio_snapshots": {"snapshot_date": "2026-06-22"},
                },
                {
                    "total_value": 100,
                    "portfolio_snapshots": {"snapshot_date": "2026-06-21"},
                },
            ]
        }
    )
    monkeypatch.setattr(
        "app.routes.portfolio_snapshots.get_supabase_client", lambda: fake
    )
    response = client.get(
        "/portfolio/snapshots/history?currency=usd", headers=_auth_header()
    )
    assert response.status_code == 200
    assert response.json()[0]["snapshot_date"] == "2026-06-21"
    calls = fake.queries["portfolio_snapshot_currency_totals"].calls
    assert ("eq", ("owner_id", OWNER_ID), {}) in calls
    assert ("eq", ("currency", "USD"), {}) in calls


def test_get_snapshot_returns_404_when_absent(monkeypatch):
    fake = FakeSupabase({"portfolio_snapshots": []})
    monkeypatch.setattr(
        "app.routes.portfolio_snapshots.get_supabase_client", lambda: fake
    )
    response = client.get(
        "/portfolio/snapshots/2026-06-22", headers=_auth_header()
    )
    assert response.status_code == 404


def test_get_snapshot_returns_header_totals_and_positions(monkeypatch):
    fake = FakeSupabase(
        {
            "portfolio_snapshots": [
                {
                    "id": "snapshot-id",
                    "snapshot_date": "2026-06-22",
                    "generated_at": "2026-06-22T12:00:00+00:00",
                    "source": "manual",
                    "partial_failure": False,
                    "broker_status_json": {"ibkr": "ok"},
                }
            ],
            "portfolio_snapshot_currency_totals": [
                {
                    "currency": "USD",
                    "market_value": 100,
                    "cash_value": 20,
                    "invested_value": 100,
                    "total_value": 120,
                    "market_value_complete": True,
                    "market_value_missing": 0,
                }
            ],
            "portfolio_snapshot_positions": [
                {
                    "broker": "ibkr",
                    "account_ref": "U***4567",
                    "stable_asset_id": "265598",
                    "asset_symbol": "AAPL",
                    "asset_name": None,
                    "asset_type": "stock",
                    "instrument_id": "265598",
                    "quantity": 1,
                    "price": None,
                    "market_value": None,
                    "average_cost": None,
                    "cost_basis": None,
                    "unrealized_pnl": None,
                    "today_pnl": None,
                    "currency": "USD",
                    "allocation_pct": None,
                    "quote_status": "unknown",
                    "metadata_json": {},
                }
            ],
        }
    )
    monkeypatch.setattr(
        "app.routes.portfolio_snapshots.get_supabase_client", lambda: fake
    )
    response = client.get(
        "/portfolio/snapshots/2026-06-22", headers=_auth_header()
    )
    assert response.status_code == 200
    assert response.json()["positions"][0]["stable_asset_id"] == "265598"
    assert response.json()["positions"][0]["market_value"] is None
    for table in fake.queries.values():
        assert ("eq", ("owner_id", OWNER_ID), {}) in table.calls

