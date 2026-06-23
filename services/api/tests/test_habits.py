"""
Tests for GET /habits (Phase 20) — read-only. Confirmed habits are created by
confirm_habit_item; this router only reads them. Habits are definition-only.
"""
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.db.supabase_client import SupabaseConfigurationError
from app.main import app
from app.services.classifier import HabitStructuredJson

client = TestClient(app)

from tests.conftest import mint_test_token

VALID_TOKEN = mint_test_token()

HABIT_ROW = {
    "id": "habit-1",
    "inbox_item_id": "inbox-1",
    "owner_id": "owner-1",
    "name": "Meditate every morning",
    "cadence": "daily",
    "target": "10 min",
    "notes": None,
    "created_at": "2026-06-24T01:00:00+00:00",
}


def _auth() -> dict:
    return {"Authorization": f"Bearer {VALID_TOKEN}"}


def _list_mock(data: list) -> MagicMock:
    mock = MagicMock()
    mock.table.return_value.select.return_value.order.return_value.execute.return_value = (
        MagicMock(data=data)
    )
    return mock


def test_auth_missing_token_returns_401():
    assert client.get("/habits").status_code == 401


def test_auth_non_owner_returns_403():
    token = mint_test_token(sub="00000000-0000-0000-0000-0000000000ff")
    assert client.get("/habits", headers={"Authorization": f"Bearer {token}"}).status_code == 403


def test_empty_list():
    mock = _list_mock([])
    with patch("app.routes.habits.get_supabase_client", return_value=mock):
        res = client.get("/habits", headers=_auth())
    assert res.status_code == 200
    assert res.json() == {"items": [], "total": 0}


def test_shape_and_total():
    mock = _list_mock([HABIT_ROW])
    with patch("app.routes.habits.get_supabase_client", return_value=mock):
        res = client.get("/habits", headers=_auth())
    body = res.json()
    assert body["total"] == 1
    assert body["items"][0]["name"] == "Meditate every morning"
    assert body["items"][0]["cadence"] == "daily"
    # owner_id is ignored by the response model
    assert "owner_id" not in body["items"][0]


def test_orders_newest_first():
    mock = _list_mock([HABIT_ROW])
    with patch("app.routes.habits.get_supabase_client", return_value=mock):
        client.get("/habits", headers=_auth())
    mock.table.return_value.select.return_value.order.assert_called_once_with(
        "created_at", desc=True
    )


def test_db_config_error_returns_500():
    with patch(
        "app.routes.habits.get_supabase_client",
        side_effect=SupabaseConfigurationError("missing key"),
    ):
        assert client.get("/habits", headers=_auth()).status_code == 500


def test_query_failure_returns_503():
    mock = MagicMock()
    mock.table.return_value.select.return_value.order.return_value.execute.side_effect = (
        Exception("connection refused")
    )
    with patch("app.routes.habits.get_supabase_client", return_value=mock):
        assert client.get("/habits", headers=_auth()).status_code == 503


# --- classifier schema ---


def test_habit_schema_accepts_valid():
    m = HabitStructuredJson.model_validate(
        {"name": "Gym", "cadence": "3x a week", "target": "1h"}
    )
    assert m.name == "Gym"


def test_habit_schema_requires_name():
    with pytest.raises(Exception):
        HabitStructuredJson.model_validate({"cadence": "daily"})


def test_habit_schema_rejects_extra_field():
    with pytest.raises(Exception):
        HabitStructuredJson.model_validate({"name": "x", "streak": 5})
