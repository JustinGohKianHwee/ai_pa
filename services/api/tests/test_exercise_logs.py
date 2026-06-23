"""
Tests for GET /exercise_logs and GET /exercise_logs?date=today (Phase 18).

Exercise logs are read-only here; rows are created by the confirm_exercise_item RPC.
?date=today filtering uses created_at with USER_TIMEZONE-aware midnight boundaries.
Only "today" or no date param is accepted; any other value returns 422.
"""
from datetime import datetime as real_datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.db.supabase_client import SupabaseConfigurationError
from app.main import app
from app.services.classifier import ExerciseStructuredJson

client = TestClient(app)

from tests.conftest import mint_test_token

VALID_TOKEN = mint_test_token()

EXERCISE_ROW = {
    "id": "ex-uuid-1",
    "inbox_item_id": "inbox-uuid-1",
    "activity": "running",
    "duration_min": 28,
    "distance_km": 5,
    "sets": None,
    "reps": None,
    "intensity": "moderate",
    "calories": 320,
    "logged_at": "this morning",
    "notes": None,
    "created_at": "2026-06-22T04:30:00+00:00",
}

EXERCISE_ROW_2 = {
    "id": "ex-uuid-2",
    "inbox_item_id": "inbox-uuid-2",
    "activity": "gym - chest",
    "duration_min": 45,
    "distance_km": None,
    "sets": 4,
    "reps": 10,
    "intensity": "hard",
    "calories": 200,
    "logged_at": None,
    "notes": "felt strong",
    "created_at": "2026-06-22T01:00:00+00:00",
}


def _auth_header(token: str = VALID_TOKEN) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _make_list_mock(data: list) -> MagicMock:
    mock = MagicMock()
    (
        mock.table.return_value
        .select.return_value
        .order.return_value
        .execute.return_value
    ) = MagicMock(data=data)
    return mock


def _make_today_list_mock(data: list) -> MagicMock:
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


# --- auth ---


def test_auth_missing_token_returns_401():
    assert client.get("/exercise_logs").status_code == 401


def test_auth_wrong_token_returns_401():
    assert client.get(
        "/exercise_logs", headers={"Authorization": "Bearer wrong"}
    ).status_code == 401


# --- happy path ---


def test_empty_list_returns_empty():
    mock = _make_list_mock([])
    with patch("app.routes.exercise.get_supabase_client", return_value=mock):
        response = client.get("/exercise_logs", headers=_auth_header())
    assert response.status_code == 200
    assert response.json() == {
        "items": [],
        "total": 0,
        "totals": {"duration_min": 0.0, "distance_km": 0.0, "calories": 0.0},
    }


def test_returns_correct_shape_and_total():
    mock = _make_list_mock([EXERCISE_ROW, EXERCISE_ROW_2])
    with patch("app.routes.exercise.get_supabase_client", return_value=mock):
        response = client.get("/exercise_logs", headers=_auth_header())
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert body["items"][0]["activity"] == "running"
    assert body["items"][1]["sets"] == 4
    assert body["items"][1]["reps"] == 10


def test_totals_sum_metrics_and_skip_nulls():
    mock = _make_list_mock([EXERCISE_ROW, EXERCISE_ROW_2])
    with patch("app.routes.exercise.get_supabase_client", return_value=mock):
        response = client.get("/exercise_logs", headers=_auth_header())
    body = response.json()
    # duration 28+45, distance 5 (row2 null), calories 320+200
    assert body["totals"] == {
        "duration_min": 73.0,
        "distance_km": 5.0,
        "calories": 520.0,
    }


def test_orders_newest_first():
    mock = _make_list_mock([EXERCISE_ROW])
    with patch("app.routes.exercise.get_supabase_client", return_value=mock):
        client.get("/exercise_logs", headers=_auth_header())
    mock.table.return_value.select.return_value.order.assert_called_once_with(
        "created_at", desc=True
    )


# --- ?date=today ---


def test_today_filter_applies_sgt_midnight_boundaries_in_utc(monkeypatch):
    monkeypatch.setenv("USER_TIMEZONE", "Asia/Singapore")
    fixed_now = real_datetime(2026, 6, 22, 14, 30, 0, tzinfo=ZoneInfo("Asia/Singapore"))
    mock = _make_today_list_mock([EXERCISE_ROW])
    with (
        patch("app.routes.exercise.get_supabase_client", return_value=mock),
        patch("app.routes.exercise.datetime") as mock_dt,
    ):
        mock_dt.now.return_value = fixed_now
        mock_dt.combine.side_effect = real_datetime.combine
        response = client.get("/exercise_logs?date=today", headers=_auth_header())
    assert response.status_code == 200
    gte_args = mock.table.return_value.select.return_value.gte.call_args[0]
    lt_args = mock.table.return_value.select.return_value.gte.return_value.lt.call_args[0]
    assert "2026-06-21T16:00:00" in gte_args[1]
    assert "2026-06-22T16:00:00" in lt_args[1]


def test_no_date_param_skips_filter():
    mock = _make_list_mock([EXERCISE_ROW])
    with patch("app.routes.exercise.get_supabase_client", return_value=mock):
        client.get("/exercise_logs", headers=_auth_header())
    mock.table.return_value.select.return_value.gte.assert_not_called()


def test_unsupported_date_param_returns_422():
    response = client.get("/exercise_logs?date=yesterday", headers=_auth_header())
    assert response.status_code == 422
    assert "today" in response.json()["detail"].lower()


# --- nullable fields ---


def test_null_optional_fields_survive_roundtrip():
    row = {**EXERCISE_ROW, "distance_km": None, "intensity": None, "logged_at": None}
    mock = _make_list_mock([row])
    with patch("app.routes.exercise.get_supabase_client", return_value=mock):
        response = client.get("/exercise_logs", headers=_auth_header())
    item = response.json()["items"][0]
    assert item["distance_km"] is None
    assert item["intensity"] is None
    assert item["logged_at"] is None


# --- errors ---


def test_db_config_error_returns_500():
    with patch(
        "app.routes.exercise.get_supabase_client",
        side_effect=SupabaseConfigurationError("missing key"),
    ):
        response = client.get("/exercise_logs", headers=_auth_header())
    assert response.status_code == 500


def test_query_failure_returns_503():
    mock = MagicMock()
    mock.table.return_value.select.return_value.order.return_value.execute.side_effect = (
        Exception("connection refused")
    )
    with patch("app.routes.exercise.get_supabase_client", return_value=mock):
        response = client.get("/exercise_logs", headers=_auth_header())
    assert response.status_code == 503


# --- classifier schema ---


def test_exercise_schema_accepts_valid():
    model = ExerciseStructuredJson.model_validate(
        {"activity": "running", "duration_min": 28, "distance_km": 5, "calories": 320}
    )
    assert model.activity == "running"
    assert model.duration_min == 28


def test_exercise_schema_requires_activity():
    with pytest.raises(Exception):
        ExerciseStructuredJson.model_validate({"duration_min": 30})


def test_exercise_schema_rejects_negative_metric():
    with pytest.raises(Exception):
        ExerciseStructuredJson.model_validate({"activity": "x", "duration_min": -1})


def test_exercise_schema_rejects_extra_field():
    with pytest.raises(Exception):
        ExerciseStructuredJson.model_validate({"activity": "x", "bogus": 1})
