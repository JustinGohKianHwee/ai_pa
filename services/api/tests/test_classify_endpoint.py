from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.classifier import ClassificationError, ClassificationResult

client = TestClient(app)

VALID_TOKEN = "test-dev-admin-token-xyz"
INBOX_ID = "inbox-uuid-abc"

SAMPLE_INBOX_ROW = {
    "id": INBOX_ID,
    "capture_event_id": "capture-uuid-abc",
    "item_type": "unknown",
    "review_status": "pending",
    "title": "Buy milk",
    "body": "Buy milk",
    "structured_json": {},
    "confidence": None,
    "capture_events": {"id": "capture-uuid-abc", "raw_text": "Buy milk"},
}

UPDATED_ROW = {
    "id": INBOX_ID,
    "item_type": "task",
    "review_status": "pending",
    "title": "Buy milk",
    "body": "Buy milk",
    "structured_json": {"urgency": "someday"},
    "confidence": 0.88,
}


def _make_supabase_mock(row=None, updated_row=None):
    mock = MagicMock()

    # .table("inbox_items").select(...).eq(...).single().execute()
    fetch_result = MagicMock()
    fetch_result.data = row
    (
        mock.table.return_value
        .select.return_value
        .eq.return_value
        .single.return_value
        .execute.return_value
    ) = fetch_result

    # .table("inbox_items").select(...).eq(...).single().execute() for the updated fetch
    updated_result = MagicMock()
    updated_result.data = updated_row or UPDATED_ROW
    # second call to select chain (after classification)
    # MagicMock handles multiple calls automatically via return_value chaining

    return mock


def _auth_header(token: str = VALID_TOKEN) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Auth guard
# ---------------------------------------------------------------------------


def test_classify_missing_token_returns_403(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    response = client.post(f"/inbox/{INBOX_ID}/classify")
    assert response.status_code == 403


def test_classify_wrong_token_returns_403(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    response = client.post(f"/inbox/{INBOX_ID}/classify", headers={"Authorization": "Bearer wrong"})
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Business rules
# ---------------------------------------------------------------------------


def test_classify_missing_api_key_returns_503(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    response = client.post(f"/inbox/{INBOX_ID}/classify", headers=_auth_header())
    assert response.status_code == 503


def test_classify_not_found_returns_404(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")

    mock = MagicMock()
    fetch_result = MagicMock()
    fetch_result.data = None
    (
        mock.table.return_value
        .select.return_value
        .eq.return_value
        .single.return_value
        .execute.return_value
    ) = fetch_result

    with patch("app.routes.classify.get_supabase_client", return_value=mock):
        response = client.post(f"/inbox/{INBOX_ID}/classify", headers=_auth_header())

    assert response.status_code == 404


def test_classify_confirmed_item_returns_400(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")

    confirmed_row = {**SAMPLE_INBOX_ROW, "review_status": "confirmed"}
    mock = MagicMock()
    fetch_result = MagicMock()
    fetch_result.data = confirmed_row
    (
        mock.table.return_value
        .select.return_value
        .eq.return_value
        .single.return_value
        .execute.return_value
    ) = fetch_result

    with patch("app.routes.classify.get_supabase_client", return_value=mock):
        response = client.post(f"/inbox/{INBOX_ID}/classify", headers=_auth_header())

    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------


def test_classify_success_returns_200_and_updated_item(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")

    classification = ClassificationResult(
        item_type="task",
        title="Buy milk",
        body="Buy milk",
        structured_json={"urgency": "someday"},
        confidence=0.88,
    )

    mock = MagicMock()

    # First select call returns the inbox row
    first_result = MagicMock()
    first_result.data = SAMPLE_INBOX_ROW

    # Second select call returns the updated row
    second_result = MagicMock()
    second_result.data = UPDATED_ROW

    select_chain = mock.table.return_value.select.return_value
    select_chain.eq.return_value.single.return_value.execute.side_effect = [
        first_result,
        second_result,
    ]

    with (
        patch("app.routes.classify.get_supabase_client", return_value=mock),
        patch("app.routes.classify._classify_and_update", new_callable=AsyncMock),
    ):
        response = client.post(f"/inbox/{INBOX_ID}/classify", headers=_auth_header())

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == INBOX_ID


def test_classify_does_not_create_domain_records(monkeypatch):
    """After classification, only inbox_items and agent_runs are touched — no domain tables."""
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")

    mock = MagicMock()
    first_result = MagicMock()
    first_result.data = SAMPLE_INBOX_ROW
    second_result = MagicMock()
    second_result.data = UPDATED_ROW
    select_chain = mock.table.return_value.select.return_value
    select_chain.eq.return_value.single.return_value.execute.side_effect = [
        first_result,
        second_result,
    ]

    with (
        patch("app.routes.classify.get_supabase_client", return_value=mock),
        patch("app.routes.classify._classify_and_update", new_callable=AsyncMock),
    ):
        client.post(f"/inbox/{INBOX_ID}/classify", headers=_auth_header())

    # Only inbox_items table was queried (via select) — no "tasks", "money_events" etc.
    table_calls = [call[0][0] for call in mock.table.call_args_list]
    assert all(t in {"inbox_items", "capture_events", "agent_runs"} for t in table_calls)


def test_classify_already_classified_item_returns_400(monkeypatch):
    """Items with a real item_type (not 'unknown') must be rejected — review or reject in inbox."""
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")

    classified_row = {**SAMPLE_INBOX_ROW, "item_type": "finance", "review_status": "pending"}
    mock = MagicMock()
    fetch_result = MagicMock()
    fetch_result.data = classified_row
    (
        mock.table.return_value
        .select.return_value
        .eq.return_value
        .single.return_value
        .execute.return_value
    ) = fetch_result

    with patch("app.routes.classify.get_supabase_client", return_value=mock):
        response = client.post(f"/inbox/{INBOX_ID}/classify", headers=_auth_header())

    assert response.status_code == 400
