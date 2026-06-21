"""
Voice transcription service — converts audio bytes to text using OpenAI Whisper.

Unlike the text classifier (which has a no-key fallback result), transcription has no
meaningful fallback. Callers must guard against TranscriptionError and treat it as a
pipeline failure requiring manual intervention.

Exception hierarchy:
    TranscriptionError — Whisper API call failed or OPENAI_API_KEY not set
"""
import logging
import os

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

TRANSCRIPTION_MODEL = "whisper-1"


class TranscriptionError(Exception):
    """Whisper API call failed (network, quota, auth, missing key, etc.)."""


async def transcribe_audio(audio_data: bytes, filename: str = "voice.ogg") -> str:
    """
    Transcribe audio bytes using OpenAI Whisper.

    Returns the transcript string. May be empty — callers are responsible for
    checking ``result.strip()`` before proceeding to classification.

    Raises TranscriptionError if OPENAI_API_KEY is absent or the API call fails.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise TranscriptionError("OPENAI_API_KEY not set")

    oai = AsyncOpenAI(api_key=api_key, timeout=60.0)
    try:
        result = await oai.audio.transcriptions.create(
            model=TRANSCRIPTION_MODEL,
            file=(filename, audio_data, "audio/ogg"),
            language="en",
        )
        return result.text
    except Exception as exc:
        logger.warning("Whisper API call failed: %s", type(exc).__name__)
        raise TranscriptionError(f"API call failed: {type(exc).__name__}") from exc
