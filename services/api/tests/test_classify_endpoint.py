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
    "capture_events": {"id": "capture-uuid-abc", "raw_text": "Buy milk", "transcript": None},
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
    """Build a mock for the initial inbox fetch (no .single()). `row` is a dict or None."""
    mock = MagicMock()

    fetch_result = MagicMock()
    fetch_result.data = [row] if row is not None else []
    (
        mock.table.return_value
        .select.return_value
        .eq.return_value
        .execute.return_value
    ) = fetch_result

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
    fetch_result.data = []
    (
        mock.table.return_value
        .select.return_value
        .eq.return_value
        .execute.return_value
    ) = fetch_result

    with patch("app.routes.classify.get_supabase_client", return_value=mock):
        response = client.post(f"/inbox/{INBOX_ID}/classify", headers=_auth_header())

    assert response.status_code == 404


def test_classify_not_found_vs_db_failure(monkeypatch):
    """Empty result (0 rows) → 404; actual DB exception → 503 (distinct error paths)."""
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")

    # Not found: no exception, empty list
    mock_not_found = MagicMock()
    not_found_result = MagicMock()
    not_found_result.data = []
    (
        mock_not_found.table.return_value
        .select.return_value
        .eq.return_value
        .execute.return_value
    ) = not_found_result

    with patch("app.routes.classify.get_supabase_client", return_value=mock_not_found):
        response = client.post(f"/inbox/{INBOX_ID}/classify", headers=_auth_header())
    assert response.status_code == 404

    # DB failure: exception raised during execute
    mock_db_error = MagicMock()
    (
        mock_db_error.table.return_value
        .select.return_value
        .eq.return_value
        .execute
    ).side_effect = Exception("connection refused")

    with patch("app.routes.classify.get_supabase_client", return_value=mock_db_error):
        response = client.post(f"/inbox/{INBOX_ID}/classify", headers=_auth_header())
    assert response.status_code == 503


def test_classify_confirmed_item_returns_400(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")

    confirmed_row = {**SAMPLE_INBOX_ROW, "review_status": "confirmed"}
    mock = MagicMock()
    fetch_result = MagicMock()
    fetch_result.data = [confirmed_row]
    (
        mock.table.return_value
        .select.return_value
        .eq.return_value
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

    mock = MagicMock()

    # First execute call returns the inbox row, second returns the updated row
    first_result = MagicMock()
    first_result.data = [SAMPLE_INBOX_ROW]

    second_result = MagicMock()
    second_result.data = [UPDATED_ROW]

    select_chain = mock.table.return_value.select.return_value
    select_chain.eq.return_value.execute.side_effect = [
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
    first_result.data = [SAMPLE_INBOX_ROW]
    second_result = MagicMock()
    second_result.data = [UPDATED_ROW]
    select_chain = mock.table.return_value.select.return_value
    select_chain.eq.return_value.execute.side_effect = [
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
    fetch_result.data = [classified_row]
    (
        mock.table.return_value
        .select.return_value
        .eq.return_value
        .execute.return_value
    ) = fetch_result

    with patch("app.routes.classify.get_supabase_client", return_value=mock):
        response = client.post(f"/inbox/{INBOX_ID}/classify", headers=_auth_header())

    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Voice transcript fallback (Issue 1)
# ---------------------------------------------------------------------------


def test_classify_voice_uses_transcript_fallback(monkeypatch):
    """When body and raw_text are absent, the capture transcript is used as classification text."""
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")

    voice_row = {
        **SAMPLE_INBOX_ROW,
        "body": None,
        "capture_events": {
            "id": "capture-uuid-abc",
            "raw_text": None,
            "transcript": "Buy milk",
        },
    }

    mock = MagicMock()
    first_result = MagicMock()
    first_result.data = [voice_row]
    second_result = MagicMock()
    second_result.data = [UPDATED_ROW]
    select_chain = mock.table.return_value.select.return_value
    select_chain.eq.return_value.execute.side_effect = [first_result, second_result]

    classify_mock = AsyncMock()
    with (
        patch("app.routes.classify.get_supabase_client", return_value=mock),
        patch("app.routes.classify._classify_and_update", classify_mock),
    ):
        response = client.post(f"/inbox/{INBOX_ID}/classify", headers=_auth_header())

    assert response.status_code == 200
    assert classify_mock.call_args.kwargs["text"] == "Buy milk"


def test_classify_updated_fetch_empty_returns_503(monkeypatch):
    """If the re-fetch after classification returns no rows, return 503."""
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")

    mock = MagicMock()
    first_result = MagicMock()
    first_result.data = [SAMPLE_INBOX_ROW]
    second_result = MagicMock()
    second_result.data = []
    select_chain = mock.table.return_value.select.return_value
    select_chain.eq.return_value.execute.side_effect = [first_result, second_result]

    with (
        patch("app.routes.classify.get_supabase_client", return_value=mock),
        patch("app.routes.classify._classify_and_update", new_callable=AsyncMock),
    ):
        response = client.post(f"/inbox/{INBOX_ID}/classify", headers=_auth_header())

    assert response.status_code == 503


def test_classify_voice_body_preferred_over_transcript(monkeypatch):
    """When body is present, it takes priority over transcript."""
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")

    voice_row = {
        **SAMPLE_INBOX_ROW,
        "body": "Buy milk",
        "capture_events": {
            "id": "capture-uuid-abc",
            "raw_text": None,
            "transcript": "Buy milk (transcript version)",
        },
    }

    mock = MagicMock()
    first_result = MagicMock()
    first_result.data = [voice_row]
    second_result = MagicMock()
    second_result.data = [UPDATED_ROW]
    select_chain = mock.table.return_value.select.return_value
    select_chain.eq.return_value.execute.side_effect = [first_result, second_result]

    classify_mock = AsyncMock()
    with (
        patch("app.routes.classify.get_supabase_client", return_value=mock),
        patch("app.routes.classify._classify_and_update", classify_mock),
    ):
        response = client.post(f"/inbox/{INBOX_ID}/classify", headers=_auth_header())

    assert response.status_code == 200
    assert classify_mock.call_args.kwargs["text"] == "Buy milk"
