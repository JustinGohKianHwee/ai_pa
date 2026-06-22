from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.db.supabase_client import SupabaseConfigurationError
from app.main import app

client = TestClient(app)

from tests.conftest import mint_test_token

VALID_TOKEN = mint_test_token()


def _auth_header(token: str = VALID_TOKEN) -> dict:
    return {"Authorization": f"Bearer {token}"}


INTENT_ROW_1 = {
    "id": "calendar-uuid-1",
    "inbox_item_id": "inbox-uuid-1",
    "title": "Dinner with Zoey",
    "proposed_datetime": "next Friday 7pm",
    "location": "Jewel",
    "notes": None,
    "created_at": "2024-01-01T13:00:00+00:00",
}

INTENT_ROW_2 = {
    "id": "calendar-uuid-2",
    "inbox_item_id": "inbox-uuid-2",
    "title": "Doctor appointment",
    "proposed_datetime": "Monday 10am",
    "location": None,
    "notes": "Bring insurance card",
    "created_at": "2024-01-01T09:00:00+00:00",
}


def _make_list_mock(data: list) -> MagicMock:
    mock = MagicMock()
    result = MagicMock()
    result.data = data
    (
        mock.table.return_value
        .select.return_value
        .order.return_value
        .execute.return_value
    ) = result
    return mock


# ---------------------------------------------------------------------------
# Auth guard
# ---------------------------------------------------------------------------


def test_calendar_missing_token_returns_401(monkeypatch):
    response = client.get("/calendar_intents")
    assert response.status_code == 401


def test_calendar_wrong_token_returns_401(monkeypatch):
    response = client.get("/calendar_intents", headers={"Authorization": "Bearer wrong"})
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_calendar_empty_list_returns_zero_total(monkeypatch):
    mock = _make_list_mock([])
    with patch("app.routes.calendar.get_supabase_client", return_value=mock):
        response = client.get("/calendar_intents", headers=_auth_header())
    assert response.status_code == 200
    body = response.json()
    assert body == {"items": [], "total": 0}


def test_calendar_returns_correct_shape_and_total(monkeypatch):
    """All 7 response fields must be present and total must match items length."""
    mock = _make_list_mock([INTENT_ROW_1])
    with patch("app.routes.calendar.get_supabase_client", return_value=mock):
        response = client.get("/calendar_intents", headers=_auth_header())
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    item = body["items"][0]
    for field in ("id", "inbox_item_id", "title", "proposed_datetime", "location", "notes", "created_at"):
        assert field in item, f"missing field: {field}"
    assert item["id"] == "calendar-uuid-1"
    assert item["title"] == "Dinner with Zoey"


def test_calendar_two_items_returns_total_two(monkeypatch):
    mock = _make_list_mock([INTENT_ROW_1, INTENT_ROW_2])
    with patch("app.routes.calendar.get_supabase_client", return_value=mock):
        response = client.get("/calendar_intents", headers=_auth_header())
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert len(body["items"]) == 2


def test_calendar_ordered_newest_confirmed_first(monkeypatch):
    # Supabase returns them already ordered DESC by created_at; we verify the mock is used
    # and the order is preserved in the response.
    mock = _make_list_mock([INTENT_ROW_1, INTENT_ROW_2])
    with patch("app.routes.calendar.get_supabase_client", return_value=mock):
        response = client.get("/calendar_intents", headers=_auth_header())
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 2
    assert items[0]["created_at"] > items[1]["created_at"]
    # Verify the query used desc=True ordering
    mock.table.return_value.select.return_value.order.assert_called_once_with(
        "created_at", desc=True
    )


# ---------------------------------------------------------------------------
# Null-field roundtrips
# ---------------------------------------------------------------------------


def test_calendar_null_proposed_datetime_roundtrip(monkeypatch):
    row = {**INTENT_ROW_1, "proposed_datetime": None}
    mock = _make_list_mock([row])
    with patch("app.routes.calendar.get_supabase_client", return_value=mock):
        response = client.get("/calendar_intents", headers=_auth_header())
    assert response.json()["items"][0]["proposed_datetime"] is None


def test_calendar_null_location_roundtrip(monkeypatch):
    row = {**INTENT_ROW_1, "location": None}
    mock = _make_list_mock([row])
    with patch("app.routes.calendar.get_supabase_client", return_value=mock):
        response = client.get("/calendar_intents", headers=_auth_header())
    assert response.json()["items"][0]["location"] is None


def test_calendar_null_notes_roundtrip(monkeypatch):
    row = {**INTENT_ROW_1, "notes": None}
    mock = _make_list_mock([row])
    with patch("app.routes.calendar.get_supabase_client", return_value=mock):
        response = client.get("/calendar_intents", headers=_auth_header())
    assert response.json()["items"][0]["notes"] is None


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_calendar_db_config_error_returns_500(monkeypatch):
    with patch(
        "app.routes.calendar.get_supabase_client",
        side_effect=SupabaseConfigurationError("missing key"),
    ):
        response = client.get("/calendar_intents", headers=_auth_header())
    assert response.status_code == 500


def test_calendar_db_query_failure_returns_503(monkeypatch):
    mock = MagicMock()
    (
        mock.table.return_value
        .select.return_value
        .order.return_value
        .execute
    ).side_effect = Exception("connection refused")
    with patch("app.routes.calendar.get_supabase_client", return_value=mock):
        response = client.get("/calendar_intents", headers=_auth_header())
    assert response.status_code == 503
