import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from app.services.classifier import (
    CLASSIFICATION_MODEL,
    CheckinStructuredJson,
    ClassificationError,
    ClassificationResult,
    ClassificationValidationError,
    classify_text,
)


# ---------------------------------------------------------------------------
# ClassificationResult model validation
# ---------------------------------------------------------------------------


def test_valid_result_parses_correctly():
    result = ClassificationResult(
        item_type="task",
        title="Pay credit card bill",
        body="remind me to pay my credit card bill next Friday",
        structured_json={"due_date": "next Friday", "urgency": "this_week"},
        confidence=0.92,
    )
    assert result.item_type == "task"
    assert result.confidence == 0.92


def test_invalid_item_type_raises():
    with pytest.raises(Exception):
        ClassificationResult(
            item_type="classification_failed",  # not an allowed value
            title="x",
            body="x",
            structured_json={},
            confidence=0.5,
        )


def test_title_is_truncated_to_100_chars():
    long_title = "x" * 200
    result = ClassificationResult(
        item_type="note",
        title=long_title,
        body="body",
        structured_json={"content": "body"},
        confidence=0.5,
    )
    assert len(result.title) == 100


def test_out_of_range_confidence_raises_validation_error():
    with pytest.raises(ValidationError):
        ClassificationResult(
            item_type="unknown", title="t", body="b", structured_json={}, confidence=1.5
        )
    with pytest.raises(ValidationError):
        ClassificationResult(
            item_type="unknown", title="t", body="b", structured_json={}, confidence=-0.1
        )


# ---------------------------------------------------------------------------
# Per-type structured_json validation
# ---------------------------------------------------------------------------


def test_finance_json_requires_amount():
    with pytest.raises(ValidationError):
        ClassificationResult(
            item_type="finance",
            title="t",
            body="b",
            structured_json={"currency": "SGD", "direction": "expense"},
            confidence=0.9,
        )


def test_finance_json_invalid_direction_raises():
    with pytest.raises(ValidationError):
        ClassificationResult(
            item_type="finance",
            title="t",
            body="b",
            structured_json={"amount": 12.0, "currency": "SGD", "direction": "refund"},
            confidence=0.9,
        )


def test_finance_json_zero_amount_raises():
    with pytest.raises(ValidationError):
        ClassificationResult(
            item_type="finance",
            title="t",
            body="b",
            structured_json={"amount": 0, "currency": "SGD", "direction": "expense"},
            confidence=0.9,
        )


def test_finance_json_negative_amount_raises():
    with pytest.raises(ValidationError):
        ClassificationResult(
            item_type="finance",
            title="t",
            body="b",
            structured_json={"amount": -5.0, "currency": "SGD", "direction": "expense"},
            confidence=0.9,
        )


def test_finance_json_nan_amount_raises():
    with pytest.raises(ValidationError):
        ClassificationResult(
            item_type="finance",
            title="t",
            body="b",
            structured_json={"amount": float("nan"), "currency": "SGD", "direction": "expense"},
            confidence=0.9,
        )


def test_finance_json_infinity_amount_raises():
    with pytest.raises(ValidationError):
        ClassificationResult(
            item_type="finance",
            title="t",
            body="b",
            structured_json={"amount": float("inf"), "currency": "SGD", "direction": "expense"},
            confidence=0.9,
        )


def test_task_json_invalid_urgency_raises():
    with pytest.raises(ValidationError):
        ClassificationResult(
            item_type="task",
            title="t",
            body="b",
            structured_json={"urgency": "asap"},
            confidence=0.8,
        )


def test_unknown_must_have_empty_structured_json():
    with pytest.raises(ValidationError):
        ClassificationResult(
            item_type="unknown",
            title="t",
            body="b",
            structured_json={"some_field": "oops"},
            confidence=0.0,
        )


def test_valid_finance_json_passes():
    result = ClassificationResult(
        item_type="finance",
        title="Lunch at Tanjong Pagar",
        body="Spent $12 on lunch at Tanjong Pagar",
        structured_json={"amount": 12.0, "currency": "SGD", "direction": "expense"},
        confidence=0.95,
    )
    assert result.structured_json["direction"] == "expense"


# ---------------------------------------------------------------------------
# classify_text — fallback when OPENAI_API_KEY is absent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_classify_text_returns_fallback_when_no_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = await classify_text("Buy milk")
    assert result.item_type == "unknown"
    assert result.confidence == 0.0
    assert "Buy milk" in result.body


# ---------------------------------------------------------------------------
# classify_text — successful API call (mocked)
# ---------------------------------------------------------------------------


def _make_openai_response(payload: dict) -> MagicMock:
    message = MagicMock()
    message.content = json.dumps(payload)
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


@pytest.mark.asyncio
async def test_classify_text_success_returns_parsed_result(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")
    payload = {
        "item_type": "finance",
        "title": "Lunch at Tanjong Pagar",
        "body": "spent $12.50 on lunch at Tanjong Pagar",
        "structured_json": {"amount": 12.50, "currency": "SGD", "direction": "expense"},
        "confidence": 0.95,
    }
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=_make_openai_response(payload))

    with patch("app.services.classifier.AsyncOpenAI", return_value=mock_client):
        result = await classify_text("spent $12.50 on lunch at Tanjong Pagar")

    assert result.item_type == "finance"
    assert result.confidence == 0.95
    assert result.structured_json["amount"] == 12.50
    mock_client.chat.completions.create.assert_awaited_once()
    call_kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert call_kwargs["model"] == CLASSIFICATION_MODEL
    assert call_kwargs["response_format"] == {"type": "json_object"}


# ---------------------------------------------------------------------------
# classify_text — failure cases (mocked)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_classify_text_raises_validation_error_on_invalid_json(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")
    message = MagicMock()
    message.content = "not valid json {"
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=response)

    with patch("app.services.classifier.AsyncOpenAI", return_value=mock_client):
        with pytest.raises(ClassificationValidationError):
            await classify_text("some text")


@pytest.mark.asyncio
async def test_classify_text_raises_validation_error_on_wrong_schema(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")
    payload = {"wrong_field": "nope", "confidence": 0.5}  # missing required fields

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=_make_openai_response(payload))

    with patch("app.services.classifier.AsyncOpenAI", return_value=mock_client):
        with pytest.raises(ClassificationValidationError):
            await classify_text("some text")


@pytest.mark.asyncio
async def test_classify_text_raises_classification_error_on_api_failure(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=Exception("connection refused"))

    with patch("app.services.classifier.AsyncOpenAI", return_value=mock_client):
        with pytest.raises(ClassificationError):
            await classify_text("some text")


# ---------------------------------------------------------------------------
# Phase 23b — CheckinStructuredJson validation
# ---------------------------------------------------------------------------


def test_checkin_valid_fields():
    c = CheckinStructuredJson.model_validate(
        {"energy": 4, "mood": "good", "sleep_hours": 7.5, "stress": 2, "activity": "walk"}
    )
    assert c.energy == 4 and c.stress == 2 and c.sleep_hours == 7.5


def test_checkin_out_of_range_rating_dropped_to_none():
    # 1-5 ratings are lenient: out-of-range becomes None rather than failing the capture.
    c = CheckinStructuredJson.model_validate({"energy": 9, "mood": "ok"})
    assert c.energy is None


def test_checkin_insane_sleep_hours_dropped():
    c = CheckinStructuredJson.model_validate({"sleep_hours": 99, "mood": "ok"})
    assert c.sleep_hours is None


def test_checkin_requires_at_least_one_metric():
    with pytest.raises(ValidationError):
        CheckinStructuredJson.model_validate({"as_of": "today", "notes": "nothing"})
