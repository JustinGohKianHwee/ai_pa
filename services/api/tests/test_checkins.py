"""
Phase 23b — lifestyle check-ins read route. Confirm dispatch (RPC) is covered in test_review.py;
the CheckinStructuredJson schema (1-5 ratings, at-least-one-metric) is covered in test_classifier.
"""
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.db.supabase_client import SupabaseConfigurationError
from app.main import app
from tests.conftest import mint_test_token

client = TestClient(app)
VALID_TOKEN = mint_test_token()


def _auth() -> dict:
    return {"Authorization": f"Bearer {VALID_TOKEN}"}


CHECKIN_ROW = {
    "id": "chk-1",
    "inbox_item_id": "inbox-1",
    "as_of": "today",
    "energy": 4,
    "mood": "good",
    "sleep_hours": 7.5,
    "stress": 2,
    "activity": "walked 30min",
    "notes": None,
    "created_at": "2024-01-01T12:00:00+00:00",
}


def _list_mock(rows: list) -> MagicMock:
    m = MagicMock()
    m.table.return_value.select.return_value.order.return_value.execute.return_value = MagicMock(
        data=rows
    )
    return m


def test_list_checkins_requires_auth():
    assert client.get("/checkins").status_code == 401


def test_list_checkins_returns_rows():
    mock = _list_mock([CHECKIN_ROW])
    with patch("app.routes.checkins.get_supabase_client", return_value=mock):
        res = client.get("/checkins", headers=_auth())
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 1
    assert body["items"][0]["energy"] == 4
    assert body["items"][0]["sleep_hours"] == 7.5


def test_list_checkins_db_config_500():
    with patch("app.routes.checkins.get_supabase_client",
               side_effect=SupabaseConfigurationError("x")):
        assert client.get("/checkins", headers=_auth()).status_code == 500
