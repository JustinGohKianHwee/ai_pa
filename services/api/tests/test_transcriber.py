"""
Unit tests for app.services.transcriber.

These tests mock AsyncOpenAI directly to verify the exact API call shape —
something the route-level tests cannot do because they mock transcribe_audio itself.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.transcriber import transcribe_audio, TranscriptionError

FAKE_AUDIO = b"fake-ogg-bytes"


@pytest.mark.anyio
async def test_transcribe_audio_sends_ogg_tuple_to_whisper(monkeypatch):
    """Whisper must receive file=("voice.ogg", bytes, "audio/ogg") — codec is extension-driven."""
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")

    mock_result = MagicMock()
    mock_result.text = "Hello world"
    mock_transcriptions = MagicMock()
    mock_transcriptions.create = AsyncMock(return_value=mock_result)
    mock_oai = MagicMock()
    mock_oai.audio.transcriptions = mock_transcriptions

    with patch("app.services.transcriber.AsyncOpenAI", return_value=mock_oai):
        result = await transcribe_audio(FAKE_AUDIO)

    assert result == "Hello world"
    mock_transcriptions.create.assert_called_once()
    _, kwargs = mock_transcriptions.create.call_args
    assert kwargs["model"] == "whisper-1"
    assert kwargs["file"] == ("voice.ogg", FAKE_AUDIO, "audio/ogg")
    assert kwargs["language"] == "en"


@pytest.mark.anyio
async def test_transcribe_audio_raises_when_no_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(TranscriptionError, match="OPENAI_API_KEY not set"):
        await transcribe_audio(FAKE_AUDIO)


@pytest.mark.anyio
async def test_transcribe_audio_raises_on_api_error(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")

    mock_transcriptions = MagicMock()
    mock_transcriptions.create = AsyncMock(side_effect=Exception("network error"))
    mock_oai = MagicMock()
    mock_oai.audio.transcriptions = mock_transcriptions

    with patch("app.services.transcriber.AsyncOpenAI", return_value=mock_oai):
        with pytest.raises(TranscriptionError):
            await transcribe_audio(FAKE_AUDIO)
