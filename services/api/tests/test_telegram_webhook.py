from collections import namedtuple
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.db.supabase_client import SupabaseConfigurationError
from app.main import app
from app.services.classifier import (
    ClassificationError,
    ClassificationResult,
    ClassificationValidationError,
)

client = TestClient(app)

VALID_SECRET = "test-webhook-secret-xyz"
AUTHORIZED_USER_ID = "123456789"
AUTHORIZED_USER_ID_INT = 123456789
TEST_CHAT_ID = 999
TEST_MESSAGE_ID = 42


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _valid_update(
    text: str = "Buy milk",
    message_id: int = TEST_MESSAGE_ID,
    chat_id: int = TEST_CHAT_ID,
    sender_id: int = AUTHORIZED_USER_ID_INT,
) -> dict:
    return {
        "update_id": 1001,
        "message": {
            "message_id": message_id,
            "from": {"id": sender_id, "is_bot": False, "first_name": "Justin"},
            "chat": {"id": chat_id, "type": "private"},
            "date": 1700000000,
            "text": text,
        },
    }


def _valid_headers() -> dict:
    return {"X-Telegram-Bot-Api-Secret-Token": VALID_SECRET}


SupabaseMocks = namedtuple("SupabaseMocks", ["client", "capture_table", "inbox_table", "agent_runs_table"])


def _make_supabase_mock(
    existing_capture: list | None = None,
    existing_inbox: list | None = None,
    capture_insert_id: str = "new-capture-uuid",
) -> SupabaseMocks:
    """
    Return a configured Supabase client mock with separate table mocks.

    existing_capture: data returned by the duplicate check (default [] = no duplicate)
    existing_inbox: data returned by the inbox presence check (default [] = no item)
    """
    mock = MagicMock()
    capture_table = MagicMock()
    inbox_table = MagicMock()
    agent_runs_table = MagicMock()

    def _table(name: str) -> MagicMock:
        if name == "capture_events":
            return capture_table
        if name == "agent_runs":
            return agent_runs_table
        return inbox_table

    mock.table.side_effect = _table

    # capture_events.select chain (duplicate check)
    capture_select = MagicMock()
    capture_select.eq.return_value.eq.return_value.execute.return_value.data = (
        existing_capture if existing_capture is not None else []
    )
    capture_table.select.return_value = capture_select

    # capture_events.insert chain
    capture_insert = MagicMock()
    capture_insert.execute.return_value.data = [{"id": capture_insert_id}]
    capture_table.insert.return_value = capture_insert

    # inbox_items.select chain (inbox presence check in duplicate path)
    inbox_select = MagicMock()
    inbox_select.eq.return_value.execute.return_value.data = (
        existing_inbox if existing_inbox is not None else []
    )
    inbox_table.select.return_value = inbox_select

    # inbox_items.insert chain
    inbox_insert = MagicMock()
    inbox_insert.execute.return_value.data = [{"id": "new-inbox-uuid"}]
    inbox_table.insert.return_value = inbox_insert

    return SupabaseMocks(mock, capture_table, inbox_table, agent_runs_table)


def _make_classification_result(item_type: str = "task") -> ClassificationResult:
    if item_type == "finance":
        return ClassificationResult(
            item_type="finance",
            title="Lunch at Tanjong Pagar",
            body="spent $12.50 on lunch at Tanjong Pagar",
            structured_json={"amount": 12.50, "currency": "SGD", "direction": "expense"},
            confidence=0.92,
        )
    return ClassificationResult(
        item_type=item_type,  # type: ignore[arg-type]
        title="Pay credit card bill",
        body="remind me to pay my credit card bill next Friday",
        structured_json={"due_date": "next Friday", "urgency": "this_week"},
        confidence=0.92,
    )


# ---------------------------------------------------------------------------
# Auth and config validation
# ---------------------------------------------------------------------------


def test_missing_webhook_secret_env_returns_500(monkeypatch):
    monkeypatch.delenv("TELEGRAM_WEBHOOK_SECRET", raising=False)
    monkeypatch.setenv("TELEGRAM_USER_ID", AUTHORIZED_USER_ID)
    response = client.post("/telegram/webhook", json=_valid_update(), headers=_valid_headers())
    assert response.status_code == 500


def test_missing_secret_header_returns_403(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", VALID_SECRET)
    monkeypatch.setenv("TELEGRAM_USER_ID", AUTHORIZED_USER_ID)
    response = client.post("/telegram/webhook", json=_valid_update())
    assert response.status_code == 403


def test_wrong_secret_header_returns_403(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", VALID_SECRET)
    monkeypatch.setenv("TELEGRAM_USER_ID", AUTHORIZED_USER_ID)
    response = client.post(
        "/telegram/webhook",
        json=_valid_update(),
        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong-secret"},
    )
    assert response.status_code == 403


def test_missing_user_id_env_returns_500(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", VALID_SECRET)
    monkeypatch.delenv("TELEGRAM_USER_ID", raising=False)
    response = client.post("/telegram/webhook", json=_valid_update(), headers=_valid_headers())
    assert response.status_code == 500


def test_malformed_user_id_env_returns_500(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", VALID_SECRET)
    monkeypatch.setenv("TELEGRAM_USER_ID", "not-an-integer")
    response = client.post("/telegram/webhook", json=_valid_update(), headers=_valid_headers())
    assert response.status_code == 500


# ---------------------------------------------------------------------------
# Update filtering
# ---------------------------------------------------------------------------


def test_non_message_update_returns_ignored(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", VALID_SECRET)
    monkeypatch.setenv("TELEGRAM_USER_ID", AUTHORIZED_USER_ID)
    response = client.post(
        "/telegram/webhook",
        json={"update_id": 1001, "edited_message": {"message_id": 5, "chat": {"id": 9}}},
        headers=_valid_headers(),
    )
    assert response.status_code == 200
    assert response.json()["action"] == "ignored"


def test_message_without_text_returns_ignored(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", VALID_SECRET)
    monkeypatch.setenv("TELEGRAM_USER_ID", AUTHORIZED_USER_ID)
    update = _valid_update()
    del update["message"]["text"]
    response = client.post("/telegram/webhook", json=update, headers=_valid_headers())
    assert response.status_code == 200
    assert response.json()["action"] == "ignored"


def test_unauthorized_sender_returns_ignored(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", VALID_SECRET)
    monkeypatch.setenv("TELEGRAM_USER_ID", AUTHORIZED_USER_ID)
    response = client.post(
        "/telegram/webhook",
        json=_valid_update(sender_id=888888888),
        headers=_valid_headers(),
    )
    assert response.status_code == 200
    assert response.json()["action"] == "ignored"


def test_message_with_no_from_field_returns_ignored(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", VALID_SECRET)
    monkeypatch.setenv("TELEGRAM_USER_ID", AUTHORIZED_USER_ID)
    update = _valid_update()
    del update["message"]["from"]
    response = client.post("/telegram/webhook", json=update, headers=_valid_headers())
    assert response.status_code == 200
    assert response.json()["action"] == "ignored"


# ---------------------------------------------------------------------------
# Happy path — new text message
# ---------------------------------------------------------------------------


def test_valid_text_message_returns_captured(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", VALID_SECRET)
    monkeypatch.setenv("TELEGRAM_USER_ID", AUTHORIZED_USER_ID)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

    mocks = _make_supabase_mock()
    with patch("app.routes.telegram.get_supabase_client", return_value=mocks.client):
        response = client.post("/telegram/webhook", json=_valid_update(), headers=_valid_headers())

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "action": "captured"}


def test_capture_event_inserted_with_correct_fields(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", VALID_SECRET)
    monkeypatch.setenv("TELEGRAM_USER_ID", AUTHORIZED_USER_ID)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

    mocks = _make_supabase_mock()
    with patch("app.routes.telegram.get_supabase_client", return_value=mocks.client):
        client.post("/telegram/webhook", json=_valid_update("Spent $12 on lunch"), headers=_valid_headers())

    mocks.capture_table.insert.assert_called_once()
    data = mocks.capture_table.insert.call_args[0][0]
    assert data["source"] == "telegram_text"
    assert data["source_message_id"] == f"{TEST_CHAT_ID}:{TEST_MESSAGE_ID}"
    assert data["raw_text"] == "Spent $12 on lunch"
    assert data["processing_status"] == "received"
    assert data["metadata"]["chat_id"] == TEST_CHAT_ID
    assert data["metadata"]["user_id"] == AUTHORIZED_USER_ID_INT
    assert data["metadata"]["update_id"] == 1001


def test_inbox_item_inserted_with_correct_fields(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", VALID_SECRET)
    monkeypatch.setenv("TELEGRAM_USER_ID", AUTHORIZED_USER_ID)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

    mocks = _make_supabase_mock(capture_insert_id="test-capture-uuid")
    with patch("app.routes.telegram.get_supabase_client", return_value=mocks.client):
        client.post("/telegram/webhook", json=_valid_update("Buy milk"), headers=_valid_headers())

    mocks.inbox_table.insert.assert_called_once()
    data = mocks.inbox_table.insert.call_args[0][0]
    assert data["capture_event_id"] == "test-capture-uuid"
    assert data["item_type"] == "unknown"
    assert data["review_status"] == "pending"
    assert data["title"] == "Buy milk"
    assert data["body"] == "Buy milk"
    assert data["structured_json"] == {}


def test_title_is_truncated_to_100_chars(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", VALID_SECRET)
    monkeypatch.setenv("TELEGRAM_USER_ID", AUTHORIZED_USER_ID)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

    long_text = "x" * 200
    mocks = _make_supabase_mock()
    with patch("app.routes.telegram.get_supabase_client", return_value=mocks.client):
        client.post("/telegram/webhook", json=_valid_update(long_text), headers=_valid_headers())

    data = mocks.inbox_table.insert.call_args[0][0]
    assert len(data["title"]) == 100
    assert data["body"] == long_text  # body is not truncated


# ---------------------------------------------------------------------------
# Duplicate handling
# ---------------------------------------------------------------------------


def test_duplicate_with_existing_inbox_returns_duplicate_ignored(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", VALID_SECRET)
    monkeypatch.setenv("TELEGRAM_USER_ID", AUTHORIZED_USER_ID)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

    mocks = _make_supabase_mock(
        existing_capture=[{"id": "existing-capture-uuid"}],
        existing_inbox=[{"id": "existing-inbox-uuid"}],
    )
    with patch("app.routes.telegram.get_supabase_client", return_value=mocks.client):
        response = client.post("/telegram/webhook", json=_valid_update(), headers=_valid_headers())

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "action": "duplicate_ignored"}
    mocks.capture_table.insert.assert_not_called()
    mocks.inbox_table.insert.assert_not_called()


def test_duplicate_with_missing_inbox_recovers_inbox_item(monkeypatch):
    """
    If a previous capture_event insert succeeded but inbox_item insert failed,
    a Telegram retry should detect the duplicate and complete the missing inbox_item.
    """
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", VALID_SECRET)
    monkeypatch.setenv("TELEGRAM_USER_ID", AUTHORIZED_USER_ID)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

    mocks = _make_supabase_mock(
        existing_capture=[{"id": "existing-capture-uuid"}],
        existing_inbox=[],  # inbox_item was never written
    )
    with patch("app.routes.telegram.get_supabase_client", return_value=mocks.client):
        response = client.post("/telegram/webhook", json=_valid_update(), headers=_valid_headers())

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "action": "duplicate_ignored"}
    mocks.capture_table.insert.assert_not_called()
    mocks.inbox_table.insert.assert_called_once()  # recovery insert


# ---------------------------------------------------------------------------
# Telegram reply behavior
# ---------------------------------------------------------------------------


def test_missing_bot_token_skips_reply_and_returns_captured(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", VALID_SECRET)
    monkeypatch.setenv("TELEGRAM_USER_ID", AUTHORIZED_USER_ID)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

    mocks = _make_supabase_mock()
    with patch("app.routes.telegram.get_supabase_client", return_value=mocks.client):
        response = client.post("/telegram/webhook", json=_valid_update(), headers=_valid_headers())

    assert response.status_code == 200
    assert response.json()["action"] == "captured"
    mocks.capture_table.insert.assert_called_once()
    mocks.inbox_table.insert.assert_called_once()


def test_successful_telegram_reply_uses_expected_endpoint_and_payload(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", VALID_SECRET)
    monkeypatch.setenv("TELEGRAM_USER_ID", AUTHORIZED_USER_ID)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-bot-token")

    mocks = _make_supabase_mock()
    mock_response = MagicMock()
    mock_http_client = MagicMock()
    mock_http_client.post = AsyncMock(return_value=mock_response)
    mock_context = MagicMock()
    mock_context.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_context.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("app.routes.telegram.get_supabase_client", return_value=mocks.client),
        patch("app.routes.telegram.httpx.AsyncClient", return_value=mock_context),
    ):
        response = client.post(
            "/telegram/webhook", json=_valid_update(), headers=_valid_headers()
        )

    assert response.status_code == 200
    mock_http_client.post.assert_awaited_once_with(
        "https://api.telegram.org/botfake-bot-token/sendMessage",
        json={"chat_id": TEST_CHAT_ID, "text": "✓ Captured"},
    )
    mock_response.raise_for_status.assert_called_once_with()


def test_failed_telegram_reply_does_not_fail_capture(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", VALID_SECRET)
    monkeypatch.setenv("TELEGRAM_USER_ID", AUTHORIZED_USER_ID)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-bot-token")

    mocks = _make_supabase_mock()
    with (
        patch("app.routes.telegram.get_supabase_client", return_value=mocks.client),
        patch(
            "app.routes.telegram.httpx.AsyncClient",
            side_effect=Exception("simulated network failure"),
        ),
    ):
        response = client.post("/telegram/webhook", json=_valid_update(), headers=_valid_headers())

    assert response.status_code == 200
    assert response.json()["action"] == "captured"
    mocks.capture_table.insert.assert_called_once()
    mocks.inbox_table.insert.assert_called_once()


# ---------------------------------------------------------------------------
# Isolation: /health must not require Telegram or Supabase env vars
# ---------------------------------------------------------------------------


def test_health_works_without_telegram_env_vars(monkeypatch):
    monkeypatch.delenv("TELEGRAM_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_USER_ID", raising=False)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Phase 6: AI classification in Telegram webhook
# ---------------------------------------------------------------------------


def test_classification_success_updates_inbox_item(monkeypatch):
    """When OPENAI_API_KEY is set and classification succeeds, inbox_item is updated."""
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", VALID_SECRET)
    monkeypatch.setenv("TELEGRAM_USER_ID", AUTHORIZED_USER_ID)
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

    mocks = _make_supabase_mock()
    result = _make_classification_result("finance")

    with (
        patch("app.routes.telegram.get_supabase_client", return_value=mocks.client),
        patch("app.routes.telegram.classify_text", new_callable=AsyncMock, return_value=result),
    ):
        response = client.post("/telegram/webhook", json=_valid_update(), headers=_valid_headers())

    assert response.status_code == 200
    assert response.json()["action"] == "captured"
    mocks.inbox_table.update.assert_called_once()
    update_data = mocks.inbox_table.update.call_args[0][0]
    assert update_data["item_type"] == "finance"
    assert update_data["review_status"] == "pending"
    assert "confidence" in update_data
    mocks.agent_runs_table.insert.assert_called_once()
    agent_data = mocks.agent_runs_table.insert.call_args[0][0]
    assert agent_data["agent_name"] == "text_classifier"
    assert agent_data["error_json"] is None


def test_classification_api_failure_sets_needs_manual(monkeypatch):
    """When the OpenAI API call fails, inbox_item gets needs_manual_classification."""
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", VALID_SECRET)
    monkeypatch.setenv("TELEGRAM_USER_ID", AUTHORIZED_USER_ID)
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

    mocks = _make_supabase_mock()

    with (
        patch("app.routes.telegram.get_supabase_client", return_value=mocks.client),
        patch(
            "app.routes.telegram.classify_text",
            new_callable=AsyncMock,
            side_effect=ClassificationError("API down"),
        ),
    ):
        response = client.post("/telegram/webhook", json=_valid_update(), headers=_valid_headers())

    assert response.status_code == 200
    assert response.json()["action"] == "captured"
    mocks.inbox_table.update.assert_called()
    update_data = mocks.inbox_table.update.call_args[0][0]
    assert update_data["review_status"] == "needs_manual_classification"
    assert update_data["item_type"] == "unknown"
    assert update_data["structured_json"] == {}
    assert update_data["confidence"] is None
    agent_data = mocks.agent_runs_table.insert.call_args[0][0]
    assert agent_data["error_json"]["error_type"] == "classification_failed"


def test_classification_validation_failure_sets_invalid_ai_output(monkeypatch):
    """When AI output fails Pydantic validation, capture_events gets invalid_ai_output status."""
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", VALID_SECRET)
    monkeypatch.setenv("TELEGRAM_USER_ID", AUTHORIZED_USER_ID)
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

    mocks = _make_supabase_mock()

    with (
        patch("app.routes.telegram.get_supabase_client", return_value=mocks.client),
        patch(
            "app.routes.telegram.classify_text",
            new_callable=AsyncMock,
            side_effect=ClassificationValidationError("bad schema"),
        ),
    ):
        response = client.post("/telegram/webhook", json=_valid_update(), headers=_valid_headers())

    assert response.status_code == 200
    assert response.json()["action"] == "captured"
    agent_data = mocks.agent_runs_table.insert.call_args[0][0]
    assert agent_data["error_json"]["error_type"] == "invalid_ai_output"
    capture_update = mocks.capture_table.update.call_args[0][0]
    assert capture_update["processing_status"] == "invalid_ai_output"


def test_no_api_key_sets_needs_manual_classification(monkeypatch):
    """Missing OPENAI_API_KEY must produce needs_manual_classification, not leave item pending."""
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", VALID_SECRET)
    monkeypatch.setenv("TELEGRAM_USER_ID", AUTHORIZED_USER_ID)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

    mocks = _make_supabase_mock()
    with patch("app.routes.telegram.get_supabase_client", return_value=mocks.client):
        response = client.post("/telegram/webhook", json=_valid_update(), headers=_valid_headers())

    assert response.status_code == 200
    assert response.json()["action"] == "captured"

    # inbox must be set to needs_manual_classification with stale fields cleared
    update_data = mocks.inbox_table.update.call_args[0][0]
    assert update_data["review_status"] == "needs_manual_classification"
    assert update_data["item_type"] == "unknown"

    # capture must be flagged as failed
    capture_update = mocks.capture_table.update.call_args[0][0]
    assert capture_update["processing_status"] == "classification_failed"

    # audit record must document the skip reason
    agent_data = mocks.agent_runs_table.insert.call_args[0][0]
    assert agent_data["error_json"]["reason"] == "no_api_key"


# ---------------------------------------------------------------------------
# Item 2 fix — concurrent insert conflict handled gracefully (text path)
# ---------------------------------------------------------------------------


def _make_eq_eq_select(data: list) -> MagicMock:
    """Return a select mock whose .eq().eq().execute().data returns `data`."""
    sel = MagicMock()
    sel.eq.return_value.eq.return_value.execute.return_value.data = data
    return sel


def test_concurrent_insert_conflict_text(monkeypatch):
    """If capture_events INSERT fails (unique constraint race) and a re-query finds the
    existing row with an existing inbox item, the request returns duplicate_ignored."""
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", VALID_SECRET)
    monkeypatch.setenv("TELEGRAM_USER_ID", AUTHORIZED_USER_ID)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    mocks = _make_supabase_mock()

    # The INSERT raises (unique constraint violation)
    mocks.capture_table.insert.side_effect = Exception(
        "duplicate key value violates unique constraint"
    )

    # First SELECT = pre-check (no existing capture); Second SELECT = conflict re-query (finds it)
    existing_inbox_select = MagicMock()
    existing_inbox_select.eq.return_value.execute.return_value.data = [{"id": "existing-inbox"}]
    mocks.inbox_table.select.return_value = existing_inbox_select

    mocks.capture_table.select.side_effect = [
        _make_eq_eq_select([]),                          # pre-check: no duplicate
        _make_eq_eq_select([{"id": "conflict-cap"}]),   # conflict re-query: finds row
    ]

    with patch("app.routes.telegram.get_supabase_client", return_value=mocks.client):
        response = client.post("/telegram/webhook", json=_valid_update(), headers=_valid_headers())

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "action": "duplicate_ignored"}
    mocks.inbox_table.insert.assert_not_called()  # inbox already existed


def test_inbox_insert_conflict_text_continues_classification(monkeypatch):
    """If inbox_items INSERT fails (unique conflict — a concurrent recovery stub was
    inserted between capture and inbox insert), the winning request fetches the existing
    inbox_id and continues classification rather than failing or returning duplicate_ignored."""
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", VALID_SECRET)
    monkeypatch.setenv("TELEGRAM_USER_ID", AUTHORIZED_USER_ID)
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

    mocks = _make_supabase_mock(
        capture_insert_id="race-capture-uuid",
        existing_inbox=[{"id": "recovery-stub-inbox-uuid"}],
    )

    # Make the inbox INSERT raise (unique constraint on capture_event_id)
    inbox_insert_mock = MagicMock()
    inbox_insert_mock.execute.side_effect = Exception("unique constraint on capture_event_id")
    mocks.inbox_table.insert.return_value = inbox_insert_mock

    with (
        patch("app.routes.telegram.get_supabase_client", return_value=mocks.client),
        patch(
            "app.routes.telegram.classify_text",
            new_callable=AsyncMock,
            return_value=_make_classification_result(),
        ) as mock_classify,
    ):
        response = client.post("/telegram/webhook", json=_valid_update(), headers=_valid_headers())

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "action": "captured"}
    mock_classify.assert_called_once()  # classification continued using recovery-stub-inbox-uuid


def test_text_recovery_insert_failure_without_existing_inbox_is_raised(monkeypatch):
    """A non-unique recovery failure must not be reported as duplicate_ignored."""
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", VALID_SECRET)
    monkeypatch.setenv("TELEGRAM_USER_ID", AUTHORIZED_USER_ID)

    mocks = _make_supabase_mock(
        existing_capture=[{"id": "orphaned-text-capture"}],
        existing_inbox=[],
    )
    mocks.inbox_table.insert.return_value.execute.side_effect = RuntimeError(
        "database write failed"
    )

    with (
        patch("app.routes.telegram.get_supabase_client", return_value=mocks.client),
        pytest.raises(RuntimeError, match="database write failed"),
    ):
        client.post("/telegram/webhook", json=_valid_update(), headers=_valid_headers())
