from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

from tests.conftest import mint_test_token

VALID_TOKEN = mint_test_token()

SAMPLE_ROW = {
    "id": "inbox-uuid-1",
    "capture_event_id": "capture-uuid-1",
    "item_type": "unknown",
    "review_status": "pending",
    "title": "Buy milk",
    "body": "Buy milk",
    "structured_json": {},
    "confidence": None,
    "created_at": "2026-06-20T10:00:00+00:00",
    "updated_at": "2026-06-20T10:00:00+00:00",
    "reviewed_at": None,
    "capture_events": {
        "source": "telegram_text",
        "raw_text": "Buy milk",
        "transcript": None,
        "processing_status": "received",
    },
}


def _make_supabase_mock(data: list | None = None) -> MagicMock:
    mock = MagicMock()
    execute_result = MagicMock()
    execute_result.data = data if data is not None else []
    (
        mock.table.return_value
        .select.return_value
        .in_.return_value
        .order.return_value
        .execute.return_value
    ) = execute_result
    return mock


def _auth_header(token: str = VALID_TOKEN) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Auth guard
# ---------------------------------------------------------------------------


def test_inbox_missing_token_header_returns_401(monkeypatch):
    response = client.get("/inbox")
    assert response.status_code == 401


def test_inbox_wrong_token_returns_401(monkeypatch):
    response = client.get("/inbox", headers={"Authorization": "Bearer wrong-token"})
    assert response.status_code == 401


def test_inbox_missing_token_env_returns_500(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    response = client.get("/inbox", headers=_auth_header())
    assert response.status_code == 500


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_inbox_empty_db_returns_200_with_empty_list(monkeypatch):
    mock = _make_supabase_mock([])
    with patch("app.routes.inbox.get_supabase_client", return_value=mock):
        response = client.get("/inbox", headers=_auth_header())
    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0}


def test_inbox_returns_items_with_correct_shape(monkeypatch):
    mock = _make_supabase_mock([SAMPLE_ROW.copy()])
    with patch("app.routes.inbox.get_supabase_client", return_value=mock):
        response = client.get("/inbox", headers=_auth_header())
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["id"] == "inbox-uuid-1"
    assert item["item_type"] == "unknown"
    assert item["review_status"] == "pending"
    assert item["title"] == "Buy milk"
    assert item["capture"]["source"] == "telegram_text"
    assert item["capture"]["raw_text"] == "Buy milk"
    assert item["capture"]["processing_status"] == "received"
    assert item["capture"]["transcript"] is None


# ---------------------------------------------------------------------------
# Query correctness
# ---------------------------------------------------------------------------


def test_inbox_filters_by_pending_and_needs_manual_classification(monkeypatch):
    mock = _make_supabase_mock()
    with patch("app.routes.inbox.get_supabase_client", return_value=mock):
        client.get("/inbox", headers=_auth_header())
    mock.table.return_value.select.return_value.in_.assert_called_once_with(
        "review_status", ["pending", "needs_manual_classification"]
    )


def test_inbox_orders_newest_first(monkeypatch):
    mock = _make_supabase_mock()
    with patch("app.routes.inbox.get_supabase_client", return_value=mock):
        client.get("/inbox", headers=_auth_header())
    mock.table.return_value.select.return_value.in_.return_value.order.assert_called_once_with(
        "created_at", desc=True
    )


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_inbox_db_error_returns_503(monkeypatch):
    mock = MagicMock()
    execute_mock = (
        mock.table.return_value
        .select.return_value
        .in_.return_value
        .order.return_value
        .execute
    )
    execute_mock.side_effect = Exception("DB connection lost")
    with patch("app.routes.inbox.get_supabase_client", return_value=mock):
        response = client.get("/inbox", headers=_auth_header())
    assert response.status_code == 503
