"""Tests for GET /financial_snapshots (Phase 22a) — read-only list of manual snapshots."""
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.db.supabase_client import SupabaseConfigurationError
from app.main import app

client = TestClient(app)

from tests.conftest import mint_test_token

VALID_TOKEN = mint_test_token()

SNAP_ROW = {
    "id": "fs-1",
    "inbox_item_id": "inbox-1",
    "owner_id": "owner-1",
    "as_of": "today",
    "monthly_income_json": [{"currency": "SGD", "amount": 8000}],
    "monthly_investment_json": [{"currency": "SGD", "amount": 2000}],
    "liquid_cash_json": [{"currency": "SGD", "amount": 25000}],
    "liabilities_json": [{"currency": "SGD", "amount": 12000}],
    "notes": None,
    "created_at": "2026-06-24T01:00:00+00:00",
}


def _auth() -> dict:
    return {"Authorization": f"Bearer {VALID_TOKEN}"}


def _list_mock(data: list) -> MagicMock:
    mock = MagicMock()
    mock.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = (
        MagicMock(data=data)
    )
    return mock


def test_auth_missing_token_returns_401():
    assert client.get("/financial_snapshots").status_code == 401


def test_auth_non_owner_returns_403():
    token = mint_test_token(sub="00000000-0000-0000-0000-0000000000ff")
    assert client.get(
        "/financial_snapshots", headers={"Authorization": f"Bearer {token}"}
    ).status_code == 403


def test_empty_list():
    mock = _list_mock([])
    with patch("app.routes.financial_snapshots.get_supabase_client", return_value=mock):
        res = client.get("/financial_snapshots", headers=_auth())
    assert res.status_code == 200
    assert res.json() == {"items": [], "total": 0}


def test_shape_and_arrays():
    mock = _list_mock([SNAP_ROW])
    with patch("app.routes.financial_snapshots.get_supabase_client", return_value=mock):
        res = client.get("/financial_snapshots", headers=_auth())
    body = res.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["monthly_income"][0] == {"currency": "SGD", "amount": 8000}
    assert item["liquid_cash"][0]["amount"] == 25000
    assert "owner_id" not in item


def test_query_failure_returns_503():
    mock = MagicMock()
    mock.table.return_value.select.return_value.eq.return_value.order.return_value.execute.side_effect = (
        Exception("boom")
    )
    with patch("app.routes.financial_snapshots.get_supabase_client", return_value=mock):
        assert client.get("/financial_snapshots", headers=_auth()).status_code == 503


def test_db_config_error_returns_500():
    with patch(
        "app.routes.financial_snapshots.get_supabase_client",
        side_effect=SupabaseConfigurationError("missing key"),
    ):
        assert client.get("/financial_snapshots", headers=_auth()).status_code == 500
