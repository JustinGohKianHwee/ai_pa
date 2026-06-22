"""
Tests for GET /food_logs and GET /food_logs?date=today.

Phase 11 food logs module — read-only. Logs are created by confirm_food_item RPC;
this router only reads them. ?date=today filtering uses created_at with USER_TIMEZONE-aware
midnight boundaries. Only "today" or no date param is accepted; any other value returns 422.
"""
from datetime import datetime as real_datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.db.supabase_client import SupabaseConfigurationError
from app.main import app

client = TestClient(app)

from tests.conftest import mint_test_token

VALID_TOKEN = mint_test_token()

FOOD_LOG_ROW = {
    "id": "food-log-uuid-1",
    "inbox_item_id": "inbox-uuid-1",
    "description": "chicken rice",
    "meal_type": "lunch",
    "logged_at": None,
    "created_at": "2026-06-22T04:30:00+00:00",
}

FOOD_LOG_ROW_2 = {
    "id": "food-log-uuid-2",
    "inbox_item_id": "inbox-uuid-2",
    "description": "kopi and toast",
    "meal_type": "breakfast",
    "logged_at": "this morning",
    "created_at": "2026-06-22T01:00:00+00:00",
}


def _auth_header(token: str = VALID_TOKEN) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _make_list_mock(data: list) -> MagicMock:
    """No date filter: table → select → order → execute"""
    mock = MagicMock()
    (
        mock.table.return_value
        .select.return_value
        .order.return_value
        .execute.return_value
    ) = MagicMock(data=data)
    return mock


def _make_today_list_mock(data: list) -> MagicMock:
    """?date=today filter: table → select → gte → lt → order → execute"""
    mock = MagicMock()
    (
        mock.table.return_value
        .select.return_value
        .gte.return_value
        .lt.return_value
        .order.return_value
        .execute.return_value
    ) = MagicMock(data=data)
    return mock


# ---------------------------------------------------------------------------
# Auth guard
# ---------------------------------------------------------------------------


def test_auth_missing_token_returns_401(monkeypatch):
    response = client.get("/food_logs")
    assert response.status_code == 401


def test_auth_wrong_token_returns_401(monkeypatch):
    response = client.get("/food_logs", headers={"Authorization": "Bearer wrong"})
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Happy path — no filter
# ---------------------------------------------------------------------------


def test_empty_list_returns_empty(monkeypatch):
    mock = _make_list_mock([])
    with patch("app.routes.food.get_supabase_client", return_value=mock):
        response = client.get("/food_logs", headers=_auth_header())
    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0}


def test_returns_correct_shape_and_total(monkeypatch):
    mock = _make_list_mock([FOOD_LOG_ROW, FOOD_LOG_ROW_2])
    with patch("app.routes.food.get_supabase_client", return_value=mock):
        response = client.get("/food_logs", headers=_auth_header())
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert body["items"][0]["id"] == "food-log-uuid-1"
    assert body["items"][0]["description"] == "chicken rice"
    assert body["items"][0]["meal_type"] == "lunch"
    assert body["items"][1]["id"] == "food-log-uuid-2"


def test_orders_newest_first(monkeypatch):
    mock = _make_list_mock([FOOD_LOG_ROW])
    with patch("app.routes.food.get_supabase_client", return_value=mock):
        client.get("/food_logs", headers=_auth_header())
    mock.table.return_value.select.return_value.order.assert_called_once_with(
        "created_at", desc=True
    )


# ---------------------------------------------------------------------------
# ?date=today — timezone-aware filtering
# ---------------------------------------------------------------------------


def test_today_filter_applies_sgt_midnight_boundaries_in_utc(monkeypatch):
    """?date=today with USER_TIMEZONE=Asia/Singapore: .gte and .lt use SGT-midnight → UTC."""
    monkeypatch.setenv("USER_TIMEZONE", "Asia/Singapore")

    # Fixed "now" = 2026-06-22 14:30:00 SGT (UTC+8).
    # SGT midnight 2026-06-22 = 2026-06-21T16:00:00+00:00 UTC
    # SGT midnight 2026-06-23 = 2026-06-22T16:00:00+00:00 UTC
    fixed_now = real_datetime(2026, 6, 22, 14, 30, 0, tzinfo=ZoneInfo("Asia/Singapore"))

    mock = _make_today_list_mock([FOOD_LOG_ROW])
    with (
        patch("app.routes.food.get_supabase_client", return_value=mock),
        patch("app.routes.food.datetime") as mock_dt,
    ):
        mock_dt.now.return_value = fixed_now
        mock_dt.combine.side_effect = real_datetime.combine
        response = client.get("/food_logs?date=today", headers=_auth_header())

    assert response.status_code == 200
    gte_args = mock.table.return_value.select.return_value.gte.call_args[0]
    lt_args = (
        mock.table.return_value.select.return_value.gte.return_value.lt.call_args[0]
    )
    assert gte_args[0] == "created_at"
    assert lt_args[0] == "created_at"
    # SGT midnight → UTC: 2026-06-21 16:00:00+00:00
    assert "2026-06-21T16:00:00" in gte_args[1]
    # Next SGT midnight → UTC: 2026-06-22 16:00:00+00:00
    assert "2026-06-22T16:00:00" in lt_args[1]


def test_no_date_param_skips_filter(monkeypatch):
    """No date param → no .gte or .lt; all logs returned."""
    mock = _make_list_mock([FOOD_LOG_ROW])
    with patch("app.routes.food.get_supabase_client", return_value=mock):
        response = client.get("/food_logs", headers=_auth_header())
    assert response.status_code == 200
    mock.table.return_value.select.return_value.gte.assert_not_called()


def test_unsupported_date_param_returns_422(monkeypatch):
    """`?date=yesterday` is rejected with 422 — no DB query is made."""
    response = client.get("/food_logs?date=yesterday", headers=_auth_header())
    assert response.status_code == 422
    assert "today" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Nullable fields
# ---------------------------------------------------------------------------


def test_null_meal_type_survives_roundtrip(monkeypatch):
    row = {**FOOD_LOG_ROW, "meal_type": None}
    mock = _make_list_mock([row])
    with patch("app.routes.food.get_supabase_client", return_value=mock):
        response = client.get("/food_logs", headers=_auth_header())
    assert response.status_code == 200
    assert response.json()["items"][0]["meal_type"] is None


def test_null_logged_at_survives_roundtrip(monkeypatch):
    row = {**FOOD_LOG_ROW, "logged_at": None}
    mock = _make_list_mock([row])
    with patch("app.routes.food.get_supabase_client", return_value=mock):
        response = client.get("/food_logs", headers=_auth_header())
    assert response.status_code == 200
    assert response.json()["items"][0]["logged_at"] is None


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_db_config_error_returns_500(monkeypatch):
    with patch(
        "app.routes.food.get_supabase_client",
        side_effect=SupabaseConfigurationError("missing key"),
    ):
        response = client.get("/food_logs", headers=_auth_header())
    assert response.status_code == 500


def test_query_failure_returns_503(monkeypatch):
    mock = MagicMock()
    mock.table.return_value.select.return_value.order.return_value.execute.side_effect = (
        Exception("connection refused")
    )
    with patch("app.routes.food.get_supabase_client", return_value=mock):
        response = client.get("/food_logs", headers=_auth_header())
    assert response.status_code == 503
