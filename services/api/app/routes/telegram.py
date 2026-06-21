import logging
import os
import secrets
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from supabase import Client

from app.db.supabase_client import SupabaseConfigurationError, get_supabase_client
from app.services.classifier import (
    ClassificationError,
    ClassificationValidationError,
    classify_text,
)
from app.services.transcriber import TRANSCRIPTION_MODEL, TranscriptionError, transcribe_audio

router = APIRouter(prefix="/telegram", tags=["telegram"])
logger = logging.getLogger(__name__)

# Whisper API hard limit — not configurable.
MAX_AUDIO_BYTES = 25 * 1024 * 1024

# ---------------------------------------------------------------------------
# Telegram update models
# Only fields the pipeline needs are declared. extra="ignore" silently drops
# all other fields so unknown update types (edited_message, callback_query,
# channel_post, sticker, photo, etc.) never crash parsing.
# ---------------------------------------------------------------------------


class TelegramChat(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: int


class TelegramUser(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: int
    is_bot: bool = False


class TelegramVoice(BaseModel):
    model_config = ConfigDict(extra="ignore")
    file_id: str
    file_unique_id: str
    duration: int = 0
    mime_type: Optional[str] = None
    file_size: Optional[int] = None


class TelegramMessage(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")
    message_id: int
    from_: Optional[TelegramUser] = Field(None, alias="from")
    chat: TelegramChat
    date: int = 0
    text: Optional[str] = None
    voice: Optional[TelegramVoice] = None


class TelegramUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    update_id: int
    message: Optional[TelegramMessage] = None


# ---------------------------------------------------------------------------
# POST /telegram/webhook
# ---------------------------------------------------------------------------


@router.post("/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: Optional[str] = Header(default=None),
) -> dict:
    # 1. Validate webhook secret (timing-safe comparison)
    expected_secret = os.getenv("TELEGRAM_WEBHOOK_SECRET")
    if not expected_secret:
        raise HTTPException(
            status_code=500,
            detail="Server misconfiguration: TELEGRAM_WEBHOOK_SECRET not set",
        )
    if not x_telegram_bot_api_secret_token or not secrets.compare_digest(
        x_telegram_bot_api_secret_token, expected_secret
    ):
        raise HTTPException(status_code=403, detail="Forbidden")

    # 2. Validate authorized sender ID is configured and is a valid integer.
    # Missing or malformed TELEGRAM_USER_ID is a server misconfiguration — fail closed
    # rather than accepting messages from any sender.
    allowed_user_id_str = os.getenv("TELEGRAM_USER_ID")
    if not allowed_user_id_str:
        raise HTTPException(
            status_code=500,
            detail="Server misconfiguration: TELEGRAM_USER_ID not set",
        )
    try:
        allowed_user_id = int(allowed_user_id_str)
    except ValueError:
        raise HTTPException(
            status_code=500,
            detail="Server misconfiguration: TELEGRAM_USER_ID must be an integer",
        )

    # 3. Parse update (unknown update types are silently dropped by extra="ignore")
    body = await request.json()
    update = TelegramUpdate.model_validate(body)

    # 4. No message → ignore
    if not update.message:
        return {"status": "ok", "action": "ignored"}

    # 5. Sender must be the authorised owner — applies to both text and voice
    sender_id = update.message.from_.id if update.message.from_ else None
    if sender_id != allowed_user_id:
        return {"status": "ok", "action": "ignored"}

    msg = update.message

    # 6. Messages with no processable content need no DB access
    if not msg.text and not msg.voice:
        return {"status": "ok", "action": "ignored"}

    # 7. Get Supabase client (only needed for text/voice capture paths)
    try:
        client = get_supabase_client()
    except SupabaseConfigurationError as exc:
        raise HTTPException(status_code=500, detail=f"Database configuration error: {exc}")

    if msg.text:
        return await _capture_text(client, update, msg)
    return await _capture_voice(client, update, msg)  # msg.voice is guaranteed non-None here


# ---------------------------------------------------------------------------
# Text capture path (Phase 4+)
# ---------------------------------------------------------------------------


def _insert_recovery_inbox(
    client: Client,
    capture_id: str,
    payload: dict[str, Any],
) -> None:
    """Insert a recovery inbox row, suppressing only a verified uniqueness race."""
    try:
        client.table("inbox_items").insert(payload).execute()
    except Exception as insert_exc:
        try:
            existing = (
                client.table("inbox_items")
                .select("id")
                .eq("capture_event_id", capture_id)
                .execute()
            )
        except Exception as lookup_exc:
            raise insert_exc from lookup_exc

        if not existing.data:
            raise insert_exc

        logger.warning(
            "inbox_items recovery stub conflict for capture %s; existing row verified",
            capture_id,
        )


async def _capture_text(client: Client, update: TelegramUpdate, msg: TelegramMessage) -> dict:
    # source_message_id uses a chat_id:message_id composite because Telegram
    # message IDs are unique only within a chat.
    source_message_id = f"{msg.chat.id}:{msg.message_id}"
    existing = (
        client.table("capture_events")
        .select("id")
        .eq("source", "telegram_text")
        .eq("source_message_id", source_message_id)
        .execute()
    )

    if existing.data:
        # Duplicate capture detected. Check whether its inbox_item also exists.
        # If a previous inbox insert failed after the capture was written,
        # the capture would be unreviewable. Recover it now.
        existing_capture_id = existing.data[0]["id"]
        inbox_check = (
            client.table("inbox_items")
            .select("id")
            .eq("capture_event_id", existing_capture_id)
            .execute()
        )
        if not inbox_check.data:
            # Partial failure recovery: complete the missing inbox_item. The helper
            # suppresses only a verified concurrent uniqueness conflict.
            _insert_recovery_inbox(
                client,
                existing_capture_id,
                {
                    "capture_event_id": existing_capture_id,
                    "item_type": "unknown",
                    "review_status": "pending",
                    "title": msg.text[:100],
                    "body": msg.text,
                    "structured_json": {},
                },
            )
        return {"status": "ok", "action": "duplicate_ignored"}

    # Insert capture_event.
    # Written before any AI work. Raw source fields are immutable ground truth;
    # processing_status starts at "received".
    # The UNIQUE constraint on (source, source_message_id) is the correctness
    # guarantee; this try/except handles the rare concurrent-retry race where two
    # requests both pass the pre-check and one loses the insert race.
    try:
        capture_result = (
            client.table("capture_events")
            .insert({
                "source": "telegram_text",
                "source_message_id": source_message_id,
                "raw_text": msg.text,
                "processing_status": "received",
                "metadata": {
                    "update_id": update.update_id,
                    "chat_id": msg.chat.id,
                    "user_id": msg.from_.id if msg.from_ else None,
                    "message_date": msg.date,
                },
            })
            .execute()
        )
        capture_id = capture_result.data[0]["id"]
    except Exception:
        logger.warning(
            "capture_events insert failed for telegram_text %s; checking for concurrent duplicate",
            source_message_id,
        )
        conflict = (
            client.table("capture_events")
            .select("id")
            .eq("source", "telegram_text")
            .eq("source_message_id", source_message_id)
            .execute()
        )
        if conflict.data:
            conflict_id = conflict.data[0]["id"]
            inbox_conflict = (
                client.table("inbox_items")
                .select("id")
                .eq("capture_event_id", conflict_id)
                .execute()
            )
            if not inbox_conflict.data:
                _insert_recovery_inbox(
                    client,
                    conflict_id,
                    {
                        "capture_event_id": conflict_id,
                        "item_type": "unknown",
                        "review_status": "pending",
                        "title": msg.text[:100],
                        "body": msg.text,
                        "structured_json": {},
                    },
                )
            return {"status": "ok", "action": "duplicate_ignored"}
        raise

    # Insert inbox_item (review gate). On UNIQUE conflict (a concurrent recovery stub
    # was inserted first), fetch the existing inbox_id and continue — the classifier
    # will overwrite the stub with the real result.
    try:
        inbox_result = client.table("inbox_items").insert({
            "capture_event_id": capture_id,
            "item_type": "unknown",
            "review_status": "pending",
            "title": msg.text[:100],
            "body": msg.text,
            "structured_json": {},
        }).execute()
        inbox_id = inbox_result.data[0]["id"]
    except Exception:
        logger.warning(
            "inbox_items insert conflict for capture %s; fetching existing inbox_id", capture_id
        )
        inbox_fetch = (
            client.table("inbox_items")
            .select("id")
            .eq("capture_event_id", capture_id)
            .execute()
        )
        if not inbox_fetch.data:
            raise
        inbox_id = inbox_fetch.data[0]["id"]

    # AI classification. Always called — when OPENAI_API_KEY is absent the helper
    # records the skip as classification_failed and marks the item needs_manual_classification
    # so it cannot be confirmed without a key.
    await _classify_and_update(
        client=client,
        text=msg.text,
        capture_id=capture_id,
        inbox_id=inbox_id,
    )

    await _send_telegram_reply(msg.chat.id)
    return {"status": "ok", "action": "captured"}


# ---------------------------------------------------------------------------
# Voice capture path (Phase 10+)
# ---------------------------------------------------------------------------


async def _capture_voice(client: Client, update: TelegramUpdate, msg: TelegramMessage) -> dict:
    voice = msg.voice  # guaranteed non-None by caller

    source_message_id = f"{msg.chat.id}:{msg.message_id}"
    existing = (
        client.table("capture_events")
        .select("id")
        .eq("source", "telegram_voice")
        .eq("source_message_id", source_message_id)
        .execute()
    )

    if existing.data:
        existing_capture_id = existing.data[0]["id"]
        inbox_check = (
            client.table("inbox_items")
            .select("id")
            .eq("capture_event_id", existing_capture_id)
            .execute()
        )
        if not inbox_check.data:
            # Partial failure recovery. Cannot re-attempt transcription without knowing
            # how far the original got. Create a needs_manual stub.
            # The helper suppresses only a verified concurrent uniqueness conflict.
            _insert_recovery_inbox(
                client,
                existing_capture_id,
                {
                    "capture_event_id": existing_capture_id,
                    "item_type": "unknown",
                    "review_status": "needs_manual_classification",
                    "title": "Voice note",
                    "body": "",
                    "structured_json": {},
                },
            )
        return {"status": "ok", "action": "duplicate_ignored"}

    # Insert capture_event before any external AI calls.
    # The UNIQUE constraint on (source, source_message_id) is the correctness
    # guarantee; this try/except handles the rare concurrent-retry race.
    try:
        capture_result = (
            client.table("capture_events")
            .insert({
                "source": "telegram_voice",
                "source_message_id": source_message_id,
                "raw_text": None,
                "audio_file_id": voice.file_id,
                "processing_status": "received",
                "metadata": {
                    "update_id": update.update_id,
                    "chat_id": msg.chat.id,
                    "user_id": msg.from_.id if msg.from_ else None,
                    "message_date": msg.date,
                    "voice_duration": voice.duration,
                },
            })
            .execute()
        )
        capture_id = capture_result.data[0]["id"]
    except Exception:
        logger.warning(
            "capture_events insert failed for telegram_voice %s; checking for concurrent duplicate",
            source_message_id,
        )
        conflict = (
            client.table("capture_events")
            .select("id")
            .eq("source", "telegram_voice")
            .eq("source_message_id", source_message_id)
            .execute()
        )
        if conflict.data:
            conflict_id = conflict.data[0]["id"]
            inbox_conflict = (
                client.table("inbox_items")
                .select("id")
                .eq("capture_event_id", conflict_id)
                .execute()
            )
            if not inbox_conflict.data:
                _insert_recovery_inbox(
                    client,
                    conflict_id,
                    {
                        "capture_event_id": conflict_id,
                        "item_type": "unknown",
                        "review_status": "needs_manual_classification",
                        "title": "Voice note",
                        "body": "",
                        "structured_json": {},
                    },
                )
            return {"status": "ok", "action": "duplicate_ignored"}
        raise

    # Insert stub inbox_item (review gate). On UNIQUE conflict (a concurrent recovery
    # stub was inserted first), fetch the existing inbox_id and continue — transcription
    # and classification will overwrite the stub.
    try:
        inbox_result = client.table("inbox_items").insert({
            "capture_event_id": capture_id,
            "item_type": "unknown",
            "review_status": "pending",
            "title": "Voice note",
            "body": "",
            "structured_json": {},
        }).execute()
        inbox_id = inbox_result.data[0]["id"]
    except Exception:
        logger.warning(
            "inbox_items insert conflict for capture %s; fetching existing inbox_id", capture_id
        )
        inbox_fetch = (
            client.table("inbox_items")
            .select("id")
            .eq("capture_event_id", capture_id)
            .execute()
        )
        if not inbox_fetch.data:
            raise
        inbox_id = inbox_fetch.data[0]["id"]

    # Transcribe. On failure _transcribe_and_update handles all DB writes and
    # returns None. On success it returns the transcript string and updates
    # capture_events.transcript.
    transcript = await _transcribe_and_update(client, voice, capture_id, inbox_id)
    if transcript:
        await _classify_and_update(
            client=client,
            text=transcript,
            capture_id=capture_id,
            inbox_id=inbox_id,
        )

    await _send_telegram_reply(msg.chat.id)
    return {"status": "ok", "action": "captured"}


# ---------------------------------------------------------------------------
# Transcription helper — called from _capture_voice
# ---------------------------------------------------------------------------


async def _transcribe_and_update(
    client: Client,
    voice: TelegramVoice,
    capture_id: str,
    inbox_id: str,
) -> Optional[str]:
    """
    Download voice from Telegram, transcribe via Whisper, update DB.

    Returns transcript string on success. On any failure applies three independent
    writes (needs_manual, transcription_failed, agent_runs error row) and returns None.
    Exactly one agent_runs row is written regardless of outcome.
    """
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    api_key = os.getenv("OPENAI_API_KEY")
    agent_input: dict[str, Any] = {"file_id": voice.file_id, "duration": voice.duration}

    def _fail(error_type: str, message: str) -> None:
        _mark_needs_manual(client, inbox_id)
        try:
            client.table("capture_events").update({
                "processing_status": "transcription_failed",
            }).eq("id", capture_id).execute()
        except Exception:
            logger.exception("Failed to update capture_events.processing_status to transcription_failed")
        try:
            client.table("agent_runs").insert({
                "capture_event_id": capture_id,
                "inbox_item_id": inbox_id,
                "agent_name": "transcriber",
                "model": TRANSCRIPTION_MODEL,
                "input_json": agent_input,
                "output_json": {},
                "error_json": {"error_type": error_type, "message": message},
            }).execute()
        except Exception:
            logger.exception("Failed to write transcription failure agent_runs audit record")

    # Config checks — no network calls needed
    if not bot_token:
        _fail("no_bot_token", "TELEGRAM_BOT_TOKEN not configured")
        return None
    if not api_key:
        _fail("no_api_key", "OPENAI_API_KEY not configured")
        return None

    # Pre-flight size check using Telegram's reported file_size (may be None)
    if voice.file_size is not None and voice.file_size > MAX_AUDIO_BYTES:
        _fail("audio_too_large", f"file_size {voice.file_size} exceeds {MAX_AUDIO_BYTES} bytes")
        return None

    # Resolve file_id to a server-side file_path
    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            resp = await http.get(
                f"https://api.telegram.org/bot{bot_token}/getFile",
                params={"file_id": voice.file_id},
            )
            resp.raise_for_status()
            file_path = resp.json()["result"]["file_path"]
    except Exception as exc:
        _fail("getfile_failed", type(exc).__name__)
        return None

    # Download audio bytes. The URL embeds the bot token — never log it.
    try:
        async with httpx.AsyncClient(timeout=30.0) as http:
            dl = await http.get(f"https://api.telegram.org/file/bot{bot_token}/{file_path}")
            dl.raise_for_status()
            audio_data: bytes = dl.content
    except Exception as exc:
        _fail("download_failed", type(exc).__name__)
        return None

    # Post-download size verification
    if len(audio_data) > MAX_AUDIO_BYTES:
        _fail("audio_too_large", f"downloaded {len(audio_data)} bytes exceeds {MAX_AUDIO_BYTES}")
        return None

    # Transcribe
    try:
        transcript = await transcribe_audio(audio_data)
    except TranscriptionError as exc:
        _fail("transcription_failed", type(exc).__name__)
        return None
    except Exception as exc:
        _fail("transcription_failed", type(exc).__name__)
        logger.exception("Unexpected error during transcription")
        return None

    # Empty transcript treated as failure
    if not transcript or not transcript.strip():
        _fail("transcription_failed", "empty transcript")
        return None

    # Persist transcript first — must succeed before classification proceeds.
    # If it fails the transcript never reaches the DB, so classification would produce
    # processing_status="classified" with transcript=null. Treat persistence failure
    # the same as any other transcription failure.
    transcript_saved = False
    try:
        client.table("capture_events").update({
            "transcript": transcript,
        }).eq("id", capture_id).execute()
        transcript_saved = True
    except Exception:
        logger.exception("Failed to update capture_events.transcript")

    if not transcript_saved:
        _fail("transcript_persistence_failed", "Failed to persist transcript to capture_events")
        return None

    # Only write the success audit row after transcript is confirmed saved.
    try:
        client.table("agent_runs").insert({
            "capture_event_id": capture_id,
            "inbox_item_id": inbox_id,
            "agent_name": "transcriber",
            "model": TRANSCRIPTION_MODEL,
            "input_json": agent_input,
            "output_json": {"transcript": transcript},
            "error_json": None,
        }).execute()
    except Exception:
        logger.exception("Failed to write transcription success agent_runs audit record")

    return transcript


# ---------------------------------------------------------------------------
# Classification helper — called from both text and voice paths
# ---------------------------------------------------------------------------


async def _classify_and_update(
    client: Client,
    text: str,
    capture_id: str,
    inbox_id: str,
) -> None:
    """
    Run AI classification and persist the result.

    No-key path → classification_failed + needs_manual_classification + agent_runs audit
    On success  → update inbox_items + set processing_status="classified"
    On API error → classification_failed + needs_manual_classification
    On bad output → invalid_ai_output + needs_manual_classification

    capture_events and agent_runs are always written independently so a failure in one
    does not suppress the other.
    """
    # When OPENAI_API_KEY is absent, treat as a configuration failure. Items must not
    # remain pending/unknown/received — they need manual intervention.
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        _mark_needs_manual(client, inbox_id)
        try:
            client.table("capture_events").update({
                "processing_status": "classification_failed",
            }).eq("id", capture_id).execute()
        except Exception:
            logger.exception("Failed to update capture_events.processing_status (no-key path)")
        try:
            client.table("agent_runs").insert({
                "capture_event_id": capture_id,
                "inbox_item_id": inbox_id,
                "agent_name": "text_classifier",
                "model": None,
                "input_json": {"text": text},
                "output_json": {},
                "error_json": {
                    "reason": "no_api_key",
                    "message": "OPENAI_API_KEY not configured",
                },
            }).execute()
        except Exception:
            logger.exception("Failed to write no-key agent_runs audit record")
        return

    agent_input: dict[str, Any] = {"text": text}
    agent_output: dict[str, Any] = {}
    agent_error: dict[str, Any] | None = None
    processing_status = "classified"

    try:
        result = await classify_text(text)

        client.table("inbox_items").update({
            "item_type": result.item_type,
            "title": result.title,
            "body": result.body,
            "structured_json": result.structured_json,
            "confidence": float(result.confidence),
            "review_status": "pending",
        }).eq("id", inbox_id).execute()

        agent_output = result.model_dump()

    except ClassificationValidationError as exc:
        processing_status = "invalid_ai_output"
        agent_error = {"error_type": "invalid_ai_output", "message": str(exc)}
        _mark_needs_manual(client, inbox_id)

    except ClassificationError as exc:
        processing_status = "classification_failed"
        agent_error = {"error_type": "classification_failed", "message": str(exc)}
        _mark_needs_manual(client, inbox_id)

    except Exception as exc:
        processing_status = "classification_failed"
        agent_error = {"error_type": "unexpected", "message": type(exc).__name__}
        _mark_needs_manual(client, inbox_id)
        logger.exception("Unexpected error during classification")

    # Independent writes — a failure in one does not suppress the other.
    try:
        client.table("capture_events").update({
            "processing_status": processing_status,
        }).eq("id", capture_id).execute()
    except Exception:
        logger.exception("Failed to update capture_events.processing_status")

    try:
        client.table("agent_runs").insert({
            "capture_event_id": capture_id,
            "inbox_item_id": inbox_id,
            "agent_name": "text_classifier",
            "model": "gpt-4o-mini",
            "input_json": agent_input,
            "output_json": agent_output,
            "error_json": agent_error,
        }).execute()
    except Exception:
        logger.exception("Failed to write agent_runs audit record")


def _mark_needs_manual(client: Client, inbox_id: str) -> None:
    try:
        client.table("inbox_items").update({
            "review_status": "needs_manual_classification",
            "item_type": "unknown",
            "structured_json": {},
            "confidence": None,
        }).eq("id", inbox_id).execute()
    except Exception:
        logger.exception("Failed to mark inbox_item as needs_manual_classification")


async def _send_telegram_reply(chat_id: int) -> None:
    """Send '✓ Captured' reply (best-effort). Never fails the capture."""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        return
    try:
        async with httpx.AsyncClient(timeout=5.0) as http_client:
            response = await http_client.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": "✓ Captured"},
            )
            response.raise_for_status()
    except Exception:
        # Do not include the exception: request URLs can contain the bot token.
        logger.warning("Telegram confirmation reply failed; capture remains stored")
