"""
Tests for GET /money_events (Phase 9 finance module).

All Supabase access is mocked. money_event creation is covered in test_review.py (the
atomic confirm_finance_item RPC); this file covers reading events and computing totals.

Multi-currency safety is explicitly tested: amounts in different currencies are never summed.
"""
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.db.supabase_client import SupabaseConfigurationError
from app.main import app

client = TestClient(app)

VALID_TOKEN = "test-dev-admin-token-xyz"

SGD_FOOD = {
    "id": "evt-1",
    "inbox_item_id": "inbox-1",
    "amount": 12.0,
    "currency": "SGD",
    "direction": "expense",
    "merchant": "Hawker",
    "category": "food",
    "occurred_at": "yesterday",
    "notes": None,
    "created_at": "2024-01-03T12:00:00+00:00",
}

SGD_TRANSPORT = {
    **SGD_FOOD,
    "id": "evt-2",
    "inbox_item_id": "inbox-2",
    "amount": 8.5,
    "category": "transport",
    "merchant": None,
    "occurred_at": None,
    "created_at": "2024-01-02T12:00:00+00:00",
}

USD_UNCATEGORIZED = {
    **SGD_FOOD,
    "id": "evt-3",
    "inbox_item_id": "inbox-3",
    "amount": 20.0,
    "currency": "USD",
    "category": None,
    "merchant": None,
    "occurred_at": None,
    "created_at": "2024-01-01T12:00:00+00:00",
}


def _auth_header(token: str = VALID_TOKEN) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _make_list_mock(data: list) -> MagicMock:
    mock = MagicMock()
    (
        mock.table.return_value
        .select.return_value
        .eq.return_value
        .order.return_value
        .execute.return_value
    ) = MagicMock(data=data)
    return mock


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def test_list_money_events_missing_token_returns_403(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    response = client.get("/money_events")
    assert response.status_code == 403


def test_list_money_events_wrong_token_returns_403(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    response = client.get("/money_events", headers={"Authorization": "Bearer wrong"})
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Read + shape + ordering
# ---------------------------------------------------------------------------


def test_list_money_events_empty_returns_empty(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    mock = _make_list_mock([])
    with patch("app.routes.finance.get_supabase_client", return_value=mock):
        response = client.get("/money_events", headers=_auth_header())
    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["total"] == 0
    assert body["totals_by_currency"] == []


def test_list_money_events_returns_shape_and_total(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    mock = _make_list_mock([SGD_FOOD, SGD_TRANSPORT])
    with patch("app.routes.finance.get_supabase_client", return_value=mock):
        response = client.get("/money_events", headers=_auth_header())
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    first = body["items"][0]
    assert first["id"] == "evt-1"
    assert first["amount"] == 12.0
    assert first["currency"] == "SGD"
    assert first["category"] == "food"


def test_list_money_events_orders_newest_first(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    mock = _make_list_mock([SGD_FOOD, SGD_TRANSPORT])
    with patch("app.routes.finance.get_supabase_client", return_value=mock):
        client.get("/money_events", headers=_auth_header())
    mock.table.return_value.select.return_value.eq.return_value.order.assert_called_once_with(
        "created_at", desc=True
    )


# ---------------------------------------------------------------------------
# Totals — grouped by currency + category, never combined across currencies
# ---------------------------------------------------------------------------


def test_totals_grouped_by_currency_and_category(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    mock = _make_list_mock([SGD_FOOD, SGD_TRANSPORT, USD_UNCATEGORIZED])
    with patch("app.routes.finance.get_supabase_client", return_value=mock):
        response = client.get("/money_events", headers=_auth_header())
    totals = response.json()["totals_by_currency"]
    by_currency = {t["currency"]: t for t in totals}
    assert set(by_currency) == {"SGD", "USD"}
    assert by_currency["SGD"]["total"] == 20.5  # 12.0 + 8.5, never + the 20 USD
    cats = {c["category"]: c["amount"] for c in by_currency["SGD"]["by_category"]}
    assert cats == {"food": 12.0, "transport": 8.5}


def test_totals_never_combine_currencies(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    mock = _make_list_mock([SGD_FOOD, USD_UNCATEGORIZED])
    with patch("app.routes.finance.get_supabase_client", return_value=mock):
        response = client.get("/money_events", headers=_auth_header())
    totals = response.json()["totals_by_currency"]
    # Two separate currency buckets; no single total equals the cross-currency sum (32.0).
    assert len(totals) == 2
    assert all(t["total"] != 32.0 for t in totals)


def test_totals_null_category_folds_to_uncategorized(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    mock = _make_list_mock([USD_UNCATEGORIZED])
    with patch("app.routes.finance.get_supabase_client", return_value=mock):
        response = client.get("/money_events", headers=_auth_header())
    usd = response.json()["totals_by_currency"][0]
    assert usd["currency"] == "USD"
    assert usd["by_category"] == [{"category": "uncategorized", "amount": 20.0}]


def test_totals_use_decimal_arithmetic(monkeypatch):
    """0.10 + 0.20 must equal 0.30 exactly — Decimal arithmetic, not binary float (0.30000…04)."""
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    e1 = {**SGD_FOOD, "id": "d1", "amount": 0.10, "category": "food"}
    e2 = {**SGD_FOOD, "id": "d2", "amount": 0.20, "category": "food"}
    mock = _make_list_mock([e1, e2])
    with patch("app.routes.finance.get_supabase_client", return_value=mock):
        response = client.get("/money_events", headers=_auth_header())
    sgd = response.json()["totals_by_currency"][0]
    assert sgd["total"] == 0.30
    assert sgd["by_category"][0] == {"category": "food", "amount": 0.30}


# ---------------------------------------------------------------------------
# Income exclusion (expense-only)
# ---------------------------------------------------------------------------


def test_income_excluded_from_items_via_db_filter(monkeypatch):
    """The query filters direction='expense' at the database, so income never reaches items."""
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    mock = _make_list_mock([SGD_FOOD])
    with patch("app.routes.finance.get_supabase_client", return_value=mock):
        client.get("/money_events", headers=_auth_header())
    mock.table.return_value.select.return_value.eq.assert_called_once_with(
        "direction", "expense"
    )


def test_income_row_excluded_from_totals(monkeypatch):
    """Even if an income row were returned, it is never added into any total."""
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    income = {
        **SGD_FOOD,
        "id": "evt-income",
        "direction": "income",
        "amount": 999.0,
        "category": "salary",
    }
    mock = _make_list_mock([SGD_FOOD, income])
    with patch("app.routes.finance.get_supabase_client", return_value=mock):
        response = client.get("/money_events", headers=_auth_header())
    sgd = next(t for t in response.json()["totals_by_currency"] if t["currency"] == "SGD")
    assert sgd["total"] == 12.0  # the 999 income is excluded
    assert all(cat["category"] != "salary" for cat in sgd["by_category"])


# ---------------------------------------------------------------------------
# Database errors
# ---------------------------------------------------------------------------


def test_list_money_events_db_config_error_returns_500(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    with patch(
        "app.routes.finance.get_supabase_client",
        side_effect=SupabaseConfigurationError("missing"),
    ):
        response = client.get("/money_events", headers=_auth_header())
    assert response.status_code == 500


def test_list_money_events_query_failure_returns_503(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    mock = MagicMock()
    mock.table.return_value.select.return_value.eq.return_value.order.return_value.execute.side_effect = Exception(
        "boom"
    )
    with patch("app.routes.finance.get_supabase_client", return_value=mock):
        response = client.get("/money_events", headers=_auth_header())
    assert response.status_code == 503
