"""
Phase 10 voice tests — Telegram voice notes through the transcription pipeline.
All Telegram, OpenAI, and Supabase calls are mocked; no real network calls.

The existing test_telegram_webhook.py (text path, 36 tests) provides text-path
regression coverage automatically — no duplication needed here.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.classifier import ClassificationResult
from app.services.transcriber import TranscriptionError

client = TestClient(app)

VALID_SECRET = "test-webhook-secret-xyz"
AUTHORIZED_USER_ID = "123456789"
AUTHORIZED_USER_ID_INT = 123456789
TEST_CHAT_ID = 999
TEST_MESSAGE_ID = 77
TEST_FILE_ID = "voice-file-id-abc123"
TEST_FILE_PATH = "voice/test_file.ogg"
FAKE_AUDIO = b"fake-ogg-audio-data"
TEST_TRANSCRIPT = "Remind me to buy milk tomorrow"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _valid_headers():
    return {"X-Telegram-Bot-Api-Secret-Token": VALID_SECRET}


def _valid_voice_update(
    file_id=TEST_FILE_ID,
    file_size=102400,  # 100 KB — well within the 25 MB limit
    duration=5,
    message_id=TEST_MESSAGE_ID,
    chat_id=TEST_CHAT_ID,
    sender_id=AUTHORIZED_USER_ID_INT,
):
    return {
        "update_id": 2001,
        "message": {
            "message_id": message_id,
            "from": {"id": sender_id, "is_bot": False, "first_name": "Justin"},
            "chat": {"id": chat_id, "type": "private"},
            "date": 1700001000,
            "voice": {
                "file_id": file_id,
                "file_unique_id": "AQADvoice",
                "duration": duration,
                "mime_type": "audio/ogg",
                "file_size": file_size,
            },
        },
    }


def _make_voice_supabase_mock(
    existing_capture=None,
    existing_inbox=None,
    capture_insert_id="new-voice-capture-uuid",
    inbox_insert_id="new-voice-inbox-uuid",
):
    mock = MagicMock()
    capture_table = MagicMock()
    inbox_table = MagicMock()
    agent_runs_table = MagicMock()

    def _table(name):
        if name == "capture_events":
            return capture_table
        if name == "agent_runs":
            return agent_runs_table
        return inbox_table

    mock.table.side_effect = _table

    # capture_events.select (voice duplicate check) — .eq().eq().execute()
    dup_select = MagicMock()
    dup_select.eq.return_value.eq.return_value.execute.return_value.data = (
        existing_capture if existing_capture is not None else []
    )
    capture_table.select.return_value = dup_select

    # capture_events.insert
    cap_insert = MagicMock()
    cap_insert.execute.return_value.data = [{"id": capture_insert_id}]
    capture_table.insert.return_value = cap_insert

    # inbox_items.select (recovery presence check) — .eq().execute()
    inbox_select = MagicMock()
    inbox_select.eq.return_value.execute.return_value.data = (
        existing_inbox if existing_inbox is not None else []
    )
    inbox_table.select.return_value = inbox_select

    # inbox_items.insert
    inbox_ins = MagicMock()
    inbox_ins.execute.return_value.data = [{"id": inbox_insert_id}]
    inbox_table.insert.return_value = inbox_ins

    return mock, capture_table, inbox_table, agent_runs_table


def _make_http_ctx(method="get", response_content=None, response_json=None, raise_on=None):
    """Return (context_manager_mock, http_client_mock, response_mock) for one httpx call."""
    resp = MagicMock()
    if response_json is not None:
        resp.json.return_value = response_json
    if response_content is not None:
        resp.content = response_content
    if raise_on is not None:
        resp.raise_for_status.side_effect = raise_on
    else:
        resp.raise_for_status.return_value = None

    http_cli = MagicMock()
    if method == "post":
        http_cli.post = AsyncMock(return_value=resp)
    else:
        http_cli.get = AsyncMock(return_value=resp)

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=http_cli)
    ctx.__aexit__ = AsyncMock(return_value=None)
    return ctx, http_cli, resp


def _make_getfile_ctx():
    ctx, _, _ = _make_http_ctx("get", response_json={"result": {"file_path": TEST_FILE_PATH}})
    return ctx


def _make_download_ctx(content=FAKE_AUDIO):
    ctx, _, _ = _make_http_ctx("get", response_content=content)
    return ctx


def _make_reply_ctx():
    ctx, _, _ = _make_http_ctx("post")
    return ctx


def _make_classification_result():
    return ClassificationResult(
        item_type="task",
        title="Buy milk tomorrow",
        body=TEST_TRANSCRIPT,
        structured_json={"title": "Buy milk tomorrow", "urgency": "this_week"},
        confidence=0.90,
    )


def _assert_transcription_failed(capture_table, inbox_table, agent_runs_table, error_type):
    """Assert the standard failure writes: needs_manual, transcription_failed, agent_runs error."""
    inbox_table.update.assert_called()
    inbox_update = inbox_table.update.call_args[0][0]
    assert inbox_update["review_status"] == "needs_manual_classification"
    assert inbox_update["item_type"] == "unknown"

    capture_table.update.assert_called()
    status_update = next(
        args[0][0]
        for args in capture_table.update.call_args_list
        if "processing_status" in args[0][0]
    )
    assert status_update["processing_status"] == "transcription_failed"

    agent_runs_table.insert.assert_called_once()
    agent_data = agent_runs_table.insert.call_args[0][0]
    assert agent_data["agent_name"] == "transcriber"
    assert agent_data["error_json"]["error_type"] == error_type


# ---------------------------------------------------------------------------
# Auth / sender guards apply to voice as well as text
# ---------------------------------------------------------------------------


def test_unauthorized_voice_message_ignored(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", VALID_SECRET)
    monkeypatch.setenv("TELEGRAM_USER_ID", AUTHORIZED_USER_ID)
    response = client.post(
        "/telegram/webhook",
        json=_valid_voice_update(sender_id=888888888),
        headers=_valid_headers(),
    )
    assert response.status_code == 200
    assert response.json()["action"] == "ignored"


def test_voice_without_from_field_ignored(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", VALID_SECRET)
    monkeypatch.setenv("TELEGRAM_USER_ID", AUTHORIZED_USER_ID)
    update = _valid_voice_update()
    del update["message"]["from"]
    response = client.post("/telegram/webhook", json=update, headers=_valid_headers())
    assert response.status_code == 200
    assert response.json()["action"] == "ignored"


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_voice_message_returns_captured(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", VALID_SECRET)
    monkeypatch.setenv("TELEGRAM_USER_ID", AUTHORIZED_USER_ID)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-bot-token")
    monkeypatch.setenv("OPENAI_API_KEY", "fake-openai-key")

    mock_client, *_ = _make_voice_supabase_mock()
    http_ctxs = [_make_getfile_ctx(), _make_download_ctx(), _make_reply_ctx()]

    with (
        patch("app.routes.telegram.get_supabase_client", return_value=mock_client),
        patch("app.routes.telegram.httpx.AsyncClient", side_effect=http_ctxs),
        patch("app.routes.telegram.transcribe_audio", new_callable=AsyncMock, return_value=TEST_TRANSCRIPT),
        patch("app.routes.telegram.classify_text", new_callable=AsyncMock, return_value=_make_classification_result()),
    ):
        response = client.post("/telegram/webhook", json=_valid_voice_update(), headers=_valid_headers())

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "action": "captured"}


def test_capture_event_fields_for_voice(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", VALID_SECRET)
    monkeypatch.setenv("TELEGRAM_USER_ID", AUTHORIZED_USER_ID)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-bot-token")
    monkeypatch.setenv("OPENAI_API_KEY", "fake-openai-key")

    mock_client, capture_table, *_ = _make_voice_supabase_mock()
    http_ctxs = [_make_getfile_ctx(), _make_download_ctx(), _make_reply_ctx()]

    with (
        patch("app.routes.telegram.get_supabase_client", return_value=mock_client),
        patch("app.routes.telegram.httpx.AsyncClient", side_effect=http_ctxs),
        patch("app.routes.telegram.transcribe_audio", new_callable=AsyncMock, return_value=TEST_TRANSCRIPT),
        patch("app.routes.telegram.classify_text", new_callable=AsyncMock, return_value=_make_classification_result()),
    ):
        client.post("/telegram/webhook", json=_valid_voice_update(), headers=_valid_headers())

    capture_table.insert.assert_called_once()
    data = capture_table.insert.call_args[0][0]
    assert data["source"] == "telegram_voice"
    assert data["raw_text"] is None
    assert data["audio_file_id"] == TEST_FILE_ID
    assert data["processing_status"] == "received"
    assert data["metadata"]["chat_id"] == TEST_CHAT_ID
    assert data["metadata"]["user_id"] == AUTHORIZED_USER_ID_INT


def test_inbox_item_stub_for_voice(monkeypatch):
    """The initial inbox_item stub uses placeholder title/body before transcription."""
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", VALID_SECRET)
    monkeypatch.setenv("TELEGRAM_USER_ID", AUTHORIZED_USER_ID)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-bot-token")
    monkeypatch.setenv("OPENAI_API_KEY", "fake-openai-key")

    mock_client, _, inbox_table, _ = _make_voice_supabase_mock()
    http_ctxs = [_make_getfile_ctx(), _make_download_ctx(), _make_reply_ctx()]

    with (
        patch("app.routes.telegram.get_supabase_client", return_value=mock_client),
        patch("app.routes.telegram.httpx.AsyncClient", side_effect=http_ctxs),
        patch("app.routes.telegram.transcribe_audio", new_callable=AsyncMock, return_value=TEST_TRANSCRIPT),
        patch("app.routes.telegram.classify_text", new_callable=AsyncMock, return_value=_make_classification_result()),
    ):
        client.post("/telegram/webhook", json=_valid_voice_update(), headers=_valid_headers())

    inbox_table.insert.assert_called_once()
    data = inbox_table.insert.call_args[0][0]
    assert data["item_type"] == "unknown"
    assert data["review_status"] == "pending"
    assert data["title"] == "Voice note"
    assert data["body"] == ""
    assert data["structured_json"] == {}


# ---------------------------------------------------------------------------
# Duplicate / idempotency
# ---------------------------------------------------------------------------


def test_duplicate_voice_replay_exact_payload(monkeypatch):
    """Replaying the exact same update_id/message_id returns duplicate_ignored; no new rows."""
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", VALID_SECRET)
    monkeypatch.setenv("TELEGRAM_USER_ID", AUTHORIZED_USER_ID)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

    mock_client, capture_table, inbox_table, _ = _make_voice_supabase_mock(
        existing_capture=[{"id": "existing-voice-capture"}],
        existing_inbox=[{"id": "existing-voice-inbox"}],
    )

    with patch("app.routes.telegram.get_supabase_client", return_value=mock_client):
        response = client.post("/telegram/webhook", json=_valid_voice_update(), headers=_valid_headers())

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "action": "duplicate_ignored"}
    capture_table.insert.assert_not_called()
    inbox_table.insert.assert_not_called()


def test_duplicate_voice_missing_inbox_recovery(monkeypatch):
    """Existing capture but no inbox → recovery stub with needs_manual_classification."""
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", VALID_SECRET)
    monkeypatch.setenv("TELEGRAM_USER_ID", AUTHORIZED_USER_ID)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

    mock_client, capture_table, inbox_table, _ = _make_voice_supabase_mock(
        existing_capture=[{"id": "existing-voice-capture"}],
        existing_inbox=[],
    )

    with patch("app.routes.telegram.get_supabase_client", return_value=mock_client):
        response = client.post("/telegram/webhook", json=_valid_voice_update(), headers=_valid_headers())

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "action": "duplicate_ignored"}
    capture_table.insert.assert_not_called()
    inbox_table.insert.assert_called_once()
    recovery = inbox_table.insert.call_args[0][0]
    assert recovery["review_status"] == "needs_manual_classification"
    assert recovery["item_type"] == "unknown"


# ---------------------------------------------------------------------------
# Transcription failure paths
# ---------------------------------------------------------------------------


def test_no_bot_token_voice(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", VALID_SECRET)
    monkeypatch.setenv("TELEGRAM_USER_ID", AUTHORIZED_USER_ID)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "fake-openai-key")

    mock_client, capture_table, inbox_table, agent_runs_table = _make_voice_supabase_mock()

    with patch("app.routes.telegram.get_supabase_client", return_value=mock_client):
        response = client.post("/telegram/webhook", json=_valid_voice_update(), headers=_valid_headers())

    assert response.status_code == 200
    assert response.json()["action"] == "captured"
    _assert_transcription_failed(capture_table, inbox_table, agent_runs_table, "no_bot_token")


def test_no_openai_key_voice(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", VALID_SECRET)
    monkeypatch.setenv("TELEGRAM_USER_ID", AUTHORIZED_USER_ID)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-bot-token")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    mock_client, capture_table, inbox_table, agent_runs_table = _make_voice_supabase_mock()
    # No download happens; bot token present so reply is attempted
    http_ctxs = [_make_reply_ctx()]

    with (
        patch("app.routes.telegram.get_supabase_client", return_value=mock_client),
        patch("app.routes.telegram.httpx.AsyncClient", side_effect=http_ctxs),
    ):
        response = client.post("/telegram/webhook", json=_valid_voice_update(), headers=_valid_headers())

    assert response.status_code == 200
    assert response.json()["action"] == "captured"
    _assert_transcription_failed(capture_table, inbox_table, agent_runs_table, "no_api_key")


def test_preflight_size_check_skips_download(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", VALID_SECRET)
    monkeypatch.setenv("TELEGRAM_USER_ID", AUTHORIZED_USER_ID)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-bot-token")
    monkeypatch.setenv("OPENAI_API_KEY", "fake-openai-key")

    mock_client, capture_table, inbox_table, agent_runs_table = _make_voice_supabase_mock()
    oversized = _valid_voice_update(file_size=26 * 1024 * 1024)  # 26 MB > 25 MB limit
    # Pre-flight check stops before getFile/download; only reply ctx needed
    http_ctxs = [_make_reply_ctx()]

    with (
        patch("app.routes.telegram.get_supabase_client", return_value=mock_client),
        patch("app.routes.telegram.httpx.AsyncClient", side_effect=http_ctxs),
    ):
        response = client.post("/telegram/webhook", json=oversized, headers=_valid_headers())

    assert response.status_code == 200
    assert response.json()["action"] == "captured"
    _assert_transcription_failed(capture_table, inbox_table, agent_runs_table, "audio_too_large")


def test_post_download_size_check(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", VALID_SECRET)
    monkeypatch.setenv("TELEGRAM_USER_ID", AUTHORIZED_USER_ID)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-bot-token")
    monkeypatch.setenv("OPENAI_API_KEY", "fake-openai-key")

    oversized_bytes = b"x" * (26 * 1024 * 1024)  # 26 MB — passes pre-flight, caught post-download
    mock_client, capture_table, inbox_table, agent_runs_table = _make_voice_supabase_mock()
    http_ctxs = [_make_getfile_ctx(), _make_download_ctx(content=oversized_bytes), _make_reply_ctx()]

    with (
        patch("app.routes.telegram.get_supabase_client", return_value=mock_client),
        patch("app.routes.telegram.httpx.AsyncClient", side_effect=http_ctxs),
    ):
        response = client.post("/telegram/webhook", json=_valid_voice_update(), headers=_valid_headers())

    assert response.status_code == 200
    assert response.json()["action"] == "captured"
    _assert_transcription_failed(capture_table, inbox_table, agent_runs_table, "audio_too_large")


def test_getfile_failure(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", VALID_SECRET)
    monkeypatch.setenv("TELEGRAM_USER_ID", AUTHORIZED_USER_ID)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-bot-token")
    monkeypatch.setenv("OPENAI_API_KEY", "fake-openai-key")

    mock_client, capture_table, inbox_table, agent_runs_table = _make_voice_supabase_mock()
    fail_ctx, _, _ = _make_http_ctx("get", raise_on=Exception("Telegram API error"))
    http_ctxs = [fail_ctx, _make_reply_ctx()]

    with (
        patch("app.routes.telegram.get_supabase_client", return_value=mock_client),
        patch("app.routes.telegram.httpx.AsyncClient", side_effect=http_ctxs),
    ):
        response = client.post("/telegram/webhook", json=_valid_voice_update(), headers=_valid_headers())

    assert response.status_code == 200
    assert response.json()["action"] == "captured"
    _assert_transcription_failed(capture_table, inbox_table, agent_runs_table, "getfile_failed")


def test_audio_download_failure(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", VALID_SECRET)
    monkeypatch.setenv("TELEGRAM_USER_ID", AUTHORIZED_USER_ID)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-bot-token")
    monkeypatch.setenv("OPENAI_API_KEY", "fake-openai-key")

    mock_client, capture_table, inbox_table, agent_runs_table = _make_voice_supabase_mock()
    fail_dl_ctx, _, _ = _make_http_ctx("get", response_content=b"", raise_on=Exception("download error"))
    http_ctxs = [_make_getfile_ctx(), fail_dl_ctx, _make_reply_ctx()]

    with (
        patch("app.routes.telegram.get_supabase_client", return_value=mock_client),
        patch("app.routes.telegram.httpx.AsyncClient", side_effect=http_ctxs),
    ):
        response = client.post("/telegram/webhook", json=_valid_voice_update(), headers=_valid_headers())

    assert response.status_code == 200
    assert response.json()["action"] == "captured"
    _assert_transcription_failed(capture_table, inbox_table, agent_runs_table, "download_failed")


def test_transcription_api_failure(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", VALID_SECRET)
    monkeypatch.setenv("TELEGRAM_USER_ID", AUTHORIZED_USER_ID)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-bot-token")
    monkeypatch.setenv("OPENAI_API_KEY", "fake-openai-key")

    mock_client, capture_table, inbox_table, agent_runs_table = _make_voice_supabase_mock()
    http_ctxs = [_make_getfile_ctx(), _make_download_ctx(), _make_reply_ctx()]

    with (
        patch("app.routes.telegram.get_supabase_client", return_value=mock_client),
        patch("app.routes.telegram.httpx.AsyncClient", side_effect=http_ctxs),
        patch("app.routes.telegram.transcribe_audio",
              new_callable=AsyncMock, side_effect=TranscriptionError("Whisper API down")),
    ):
        response = client.post("/telegram/webhook", json=_valid_voice_update(), headers=_valid_headers())

    assert response.status_code == 200
    assert response.json()["action"] == "captured"
    _assert_transcription_failed(capture_table, inbox_table, agent_runs_table, "transcription_failed")


def test_empty_transcript(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", VALID_SECRET)
    monkeypatch.setenv("TELEGRAM_USER_ID", AUTHORIZED_USER_ID)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-bot-token")
    monkeypatch.setenv("OPENAI_API_KEY", "fake-openai-key")

    mock_client, capture_table, inbox_table, agent_runs_table = _make_voice_supabase_mock()
    http_ctxs = [_make_getfile_ctx(), _make_download_ctx(), _make_reply_ctx()]

    with (
        patch("app.routes.telegram.get_supabase_client", return_value=mock_client),
        patch("app.routes.telegram.httpx.AsyncClient", side_effect=http_ctxs),
        patch("app.routes.telegram.transcribe_audio", new_callable=AsyncMock, return_value=""),
        patch("app.routes.telegram.classify_text") as mock_classify,
    ):
        client.post("/telegram/webhook", json=_valid_voice_update(), headers=_valid_headers())
        mock_classify.assert_not_called()

    _assert_transcription_failed(capture_table, inbox_table, agent_runs_table, "transcription_failed")


def test_whitespace_only_transcript(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", VALID_SECRET)
    monkeypatch.setenv("TELEGRAM_USER_ID", AUTHORIZED_USER_ID)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-bot-token")
    monkeypatch.setenv("OPENAI_API_KEY", "fake-openai-key")

    mock_client, capture_table, inbox_table, agent_runs_table = _make_voice_supabase_mock()
    http_ctxs = [_make_getfile_ctx(), _make_download_ctx(), _make_reply_ctx()]

    with (
        patch("app.routes.telegram.get_supabase_client", return_value=mock_client),
        patch("app.routes.telegram.httpx.AsyncClient", side_effect=http_ctxs),
        patch("app.routes.telegram.transcribe_audio", new_callable=AsyncMock, return_value="  \n  "),
        patch("app.routes.telegram.classify_text") as mock_classify,
    ):
        client.post("/telegram/webhook", json=_valid_voice_update(), headers=_valid_headers())
        mock_classify.assert_not_called()

    _assert_transcription_failed(capture_table, inbox_table, agent_runs_table, "transcription_failed")


# ---------------------------------------------------------------------------
# Successful transcription — classifier interaction and audit trail
# ---------------------------------------------------------------------------


def test_successful_transcription_calls_classifier(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", VALID_SECRET)
    monkeypatch.setenv("TELEGRAM_USER_ID", AUTHORIZED_USER_ID)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-bot-token")
    monkeypatch.setenv("OPENAI_API_KEY", "fake-openai-key")

    mock_client, *_ = _make_voice_supabase_mock()
    http_ctxs = [_make_getfile_ctx(), _make_download_ctx(), _make_reply_ctx()]

    with (
        patch("app.routes.telegram.get_supabase_client", return_value=mock_client),
        patch("app.routes.telegram.httpx.AsyncClient", side_effect=http_ctxs),
        patch("app.routes.telegram.transcribe_audio", new_callable=AsyncMock, return_value=TEST_TRANSCRIPT),
        patch("app.routes.telegram.classify_text",
              new_callable=AsyncMock, return_value=_make_classification_result()) as mock_classify,
    ):
        client.post("/telegram/webhook", json=_valid_voice_update(), headers=_valid_headers())

    mock_classify.assert_called_once_with(TEST_TRANSCRIPT)


def test_two_agent_runs_on_happy_path(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", VALID_SECRET)
    monkeypatch.setenv("TELEGRAM_USER_ID", AUTHORIZED_USER_ID)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-bot-token")
    monkeypatch.setenv("OPENAI_API_KEY", "fake-openai-key")

    mock_client, _, _, agent_runs_table = _make_voice_supabase_mock()
    http_ctxs = [_make_getfile_ctx(), _make_download_ctx(), _make_reply_ctx()]

    with (
        patch("app.routes.telegram.get_supabase_client", return_value=mock_client),
        patch("app.routes.telegram.httpx.AsyncClient", side_effect=http_ctxs),
        patch("app.routes.telegram.transcribe_audio", new_callable=AsyncMock, return_value=TEST_TRANSCRIPT),
        patch("app.routes.telegram.classify_text",
              new_callable=AsyncMock, return_value=_make_classification_result()),
    ):
        client.post("/telegram/webhook", json=_valid_voice_update(), headers=_valid_headers())

    assert agent_runs_table.insert.call_count == 2
    first = agent_runs_table.insert.call_args_list[0][0][0]
    second = agent_runs_table.insert.call_args_list[1][0][0]
    assert first["agent_name"] == "transcriber"
    assert second["agent_name"] == "text_classifier"


def test_transcriber_agent_run_fields(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", VALID_SECRET)
    monkeypatch.setenv("TELEGRAM_USER_ID", AUTHORIZED_USER_ID)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-bot-token")
    monkeypatch.setenv("OPENAI_API_KEY", "fake-openai-key")

    mock_client, _, _, agent_runs_table = _make_voice_supabase_mock()
    http_ctxs = [_make_getfile_ctx(), _make_download_ctx(), _make_reply_ctx()]

    with (
        patch("app.routes.telegram.get_supabase_client", return_value=mock_client),
        patch("app.routes.telegram.httpx.AsyncClient", side_effect=http_ctxs),
        patch("app.routes.telegram.transcribe_audio", new_callable=AsyncMock, return_value=TEST_TRANSCRIPT),
        patch("app.routes.telegram.classify_text",
              new_callable=AsyncMock, return_value=_make_classification_result()),
    ):
        client.post("/telegram/webhook", json=_valid_voice_update(), headers=_valid_headers())

    transcriber_row = agent_runs_table.insert.call_args_list[0][0][0]
    assert transcriber_row["agent_name"] == "transcriber"
    assert transcriber_row["model"] == "whisper-1"
    assert transcriber_row["output_json"] == {"transcript": TEST_TRANSCRIPT}
    assert transcriber_row["error_json"] is None


def test_transcript_stored_in_capture_event(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", VALID_SECRET)
    monkeypatch.setenv("TELEGRAM_USER_ID", AUTHORIZED_USER_ID)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-bot-token")
    monkeypatch.setenv("OPENAI_API_KEY", "fake-openai-key")

    mock_client, capture_table, *_ = _make_voice_supabase_mock()
    http_ctxs = [_make_getfile_ctx(), _make_download_ctx(), _make_reply_ctx()]

    with (
        patch("app.routes.telegram.get_supabase_client", return_value=mock_client),
        patch("app.routes.telegram.httpx.AsyncClient", side_effect=http_ctxs),
        patch("app.routes.telegram.transcribe_audio", new_callable=AsyncMock, return_value=TEST_TRANSCRIPT),
        patch("app.routes.telegram.classify_text",
              new_callable=AsyncMock, return_value=_make_classification_result()),
    ):
        client.post("/telegram/webhook", json=_valid_voice_update(), headers=_valid_headers())

    transcript_update = next(
        args[0][0]
        for args in capture_table.update.call_args_list
        if "transcript" in args[0][0]
    )
    assert transcript_update["transcript"] == TEST_TRANSCRIPT


def test_ogg_filename_and_mime_in_whisper_call(monkeypatch):
    """transcribe_audio receives the downloaded bytes with no explicit filename kwarg,
    meaning transcriber.py uses its default 'voice.ogg' / 'audio/ogg' convention."""
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", VALID_SECRET)
    monkeypatch.setenv("TELEGRAM_USER_ID", AUTHORIZED_USER_ID)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-bot-token")
    monkeypatch.setenv("OPENAI_API_KEY", "fake-openai-key")

    mock_client, *_ = _make_voice_supabase_mock()
    http_ctxs = [_make_getfile_ctx(), _make_download_ctx(content=FAKE_AUDIO), _make_reply_ctx()]

    with (
        patch("app.routes.telegram.get_supabase_client", return_value=mock_client),
        patch("app.routes.telegram.httpx.AsyncClient", side_effect=http_ctxs),
        patch("app.routes.telegram.transcribe_audio",
              new_callable=AsyncMock, return_value=TEST_TRANSCRIPT) as mock_transcribe,
        patch("app.routes.telegram.classify_text",
              new_callable=AsyncMock, return_value=_make_classification_result()),
    ):
        client.post("/telegram/webhook", json=_valid_voice_update(), headers=_valid_headers())

    mock_transcribe.assert_called_once()
    args, kwargs = mock_transcribe.call_args
    assert args[0] == FAKE_AUDIO          # correct audio bytes
    assert "filename" not in kwargs        # default "voice.ogg" in transcriber.py is used


# ---------------------------------------------------------------------------
# Item 1 fix — transcript persistence failure must block classification
# ---------------------------------------------------------------------------


def test_transcript_persistence_failure_prevents_classification(monkeypatch):
    """If capture_events.transcript UPDATE fails, classification must not run and the
    item is marked transcription_failed / needs_manual_classification."""
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", VALID_SECRET)
    monkeypatch.setenv("TELEGRAM_USER_ID", AUTHORIZED_USER_ID)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-bot-token")
    monkeypatch.setenv("OPENAI_API_KEY", "fake-openai-key")

    mock_client, capture_table, inbox_table, agent_runs_table = _make_voice_supabase_mock()

    # Make capture_events.update raise only when persisting the transcript
    def _update_raises_on_transcript(data):
        if "transcript" in data:
            raise Exception("DB write failed")
        return MagicMock()

    capture_table.update.side_effect = _update_raises_on_transcript

    http_ctxs = [_make_getfile_ctx(), _make_download_ctx(), _make_reply_ctx()]

    with (
        patch("app.routes.telegram.get_supabase_client", return_value=mock_client),
        patch("app.routes.telegram.httpx.AsyncClient", side_effect=http_ctxs),
        patch("app.routes.telegram.transcribe_audio", new_callable=AsyncMock, return_value=TEST_TRANSCRIPT),
        patch("app.routes.telegram.classify_text") as mock_classify,
    ):
        response = client.post("/telegram/webhook", json=_valid_voice_update(), headers=_valid_headers())
        mock_classify.assert_not_called()

    assert response.status_code == 200
    assert response.json()["action"] == "captured"
    _assert_transcription_failed(
        capture_table, inbox_table, agent_runs_table, "transcript_persistence_failed"
    )


# ---------------------------------------------------------------------------
# Item 2 fix — concurrent insert conflict handled gracefully
# ---------------------------------------------------------------------------


def test_concurrent_insert_conflict_voice(monkeypatch):
    """If capture_events INSERT fails (unique constraint race) and a re-query finds the
    existing row with an existing inbox item, the request returns duplicate_ignored."""
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", VALID_SECRET)
    monkeypatch.setenv("TELEGRAM_USER_ID", AUTHORIZED_USER_ID)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

    mock_client, capture_table, inbox_table, _ = _make_voice_supabase_mock(
        existing_inbox=[{"id": "existing-voice-inbox"}],
    )

    # Make the INSERT fail, then the conflict re-query returns an existing capture
    capture_table.insert.side_effect = Exception("duplicate key value violates unique constraint")
    conflict_select = MagicMock()
    conflict_select.eq.return_value.eq.return_value.execute.return_value.data = [
        {"id": "existing-voice-capture"}
    ]
    # The first select (pre-check) returns empty; conflict re-query returns existing
    capture_table.select.side_effect = [
        _make_empty_select(),   # duplicate pre-check: no existing row
        conflict_select,        # conflict re-query: finds the row
    ]

    with patch("app.routes.telegram.get_supabase_client", return_value=mock_client):
        response = client.post("/telegram/webhook", json=_valid_voice_update(), headers=_valid_headers())

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "action": "duplicate_ignored"}
    inbox_table.insert.assert_not_called()  # inbox already exists; no new stub


def _make_empty_select():
    """Return a mock select chain whose .execute().data is []."""
    sel = MagicMock()
    sel.eq.return_value.eq.return_value.execute.return_value.data = []
    return sel


# ---------------------------------------------------------------------------
# Inbox INSERT conflict — winning request continues transcription/classification
# ---------------------------------------------------------------------------


def test_inbox_insert_conflict_voice_continues_processing(monkeypatch):
    """If inbox_items INSERT fails (unique conflict — a concurrent recovery stub was
    inserted between capture and inbox insert), the winning request fetches the existing
    inbox_id and continues transcription/classification rather than failing."""
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", VALID_SECRET)
    monkeypatch.setenv("TELEGRAM_USER_ID", AUTHORIZED_USER_ID)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-bot-token")
    monkeypatch.setenv("OPENAI_API_KEY", "fake-openai-key")

    mock_client, capture_table, inbox_table, agent_runs_table = _make_voice_supabase_mock(
        capture_insert_id="race-voice-capture-uuid",
        existing_inbox=[{"id": "recovery-stub-inbox-uuid"}],
    )

    # Make the inbox stub INSERT raise (unique constraint on capture_event_id)
    inbox_table.insert.side_effect = Exception("unique constraint on capture_event_id")

    http_ctxs = [_make_getfile_ctx(), _make_download_ctx(), _make_reply_ctx()]

    with (
        patch("app.routes.telegram.get_supabase_client", return_value=mock_client),
        patch("app.routes.telegram.httpx.AsyncClient", side_effect=http_ctxs),
        patch(
            "app.routes.telegram.transcribe_audio",
            new_callable=AsyncMock,
            return_value=TEST_TRANSCRIPT,
        ) as mock_transcribe,
        patch(
            "app.routes.telegram.classify_text",
            new_callable=AsyncMock,
            return_value=_make_classification_result(),
        ) as mock_classify,
    ):
        response = client.post("/telegram/webhook", json=_valid_voice_update(), headers=_valid_headers())

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "action": "captured"}
    mock_transcribe.assert_called_once()
    mock_classify.assert_called_once_with(TEST_TRANSCRIPT)


def test_voice_recovery_insert_failure_without_existing_inbox_is_raised(monkeypatch):
    """A non-unique recovery failure must not be reported as duplicate_ignored."""
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", VALID_SECRET)
    monkeypatch.setenv("TELEGRAM_USER_ID", AUTHORIZED_USER_ID)

    mock_client, _, inbox_table, _ = _make_voice_supabase_mock(
        existing_capture=[{"id": "orphaned-voice-capture"}],
        existing_inbox=[],
    )
    inbox_table.insert.return_value.execute.side_effect = RuntimeError("database write failed")

    with (
        patch("app.routes.telegram.get_supabase_client", return_value=mock_client),
        pytest.raises(RuntimeError, match="database write failed"),
    ):
        client.post(
            "/telegram/webhook",
            json=_valid_voice_update(),
            headers=_valid_headers(),
        )
