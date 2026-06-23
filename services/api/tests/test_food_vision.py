"""
Tests for the food vision service (Phase 17) and the extended food text schema.
The OpenAI client is mocked — no network, no real key needed.
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.food_vision import (
    FoodVisionError,
    FoodVisionValidationError,
    classify_food_image,
)
from app.services.classifier import FoodStructuredJson


def _mock_openai(content: str) -> MagicMock:
    client = MagicMock()
    message = MagicMock()
    message.content = content
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    client.chat.completions.create = AsyncMock(return_value=response)
    return client


def _food_json(**overrides) -> str:
    base = {
        "is_food": True,
        "description": "chicken rice",
        "meal_type": "lunch",
        "calories": 600,
        "protein_g": 30,
        "carbs_g": 80,
        "fat_g": 15,
        "confidence": 0.7,
    }
    base.update(overrides)
    return json.dumps(base)


@pytest.mark.asyncio
async def test_food_image_estimates(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    with patch("app.services.food_vision.AsyncOpenAI", return_value=_mock_openai(_food_json())):
        result = await classify_food_image(b"imgbytes", "had this for lunch")
    assert result.is_food is True
    assert result.description == "chicken rice"
    assert result.meal_type == "lunch"
    assert result.calories == 600
    assert result.confidence == 0.7


@pytest.mark.asyncio
async def test_not_food_result(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    content = json.dumps(
        {"is_food": False, "description": "", "meal_type": None, "confidence": 0.9}
    )
    with patch("app.services.food_vision.AsyncOpenAI", return_value=_mock_openai(content)):
        result = await classify_food_image(b"imgbytes", None)
    assert result.is_food is False
    assert result.calories is None


@pytest.mark.asyncio
async def test_no_key_falls_back_to_not_food(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = await classify_food_image(b"imgbytes", None)
    assert result.is_food is False  # never a fabricated meal without a key


@pytest.mark.asyncio
async def test_malformed_output_raises_validation(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    with patch("app.services.food_vision.AsyncOpenAI", return_value=_mock_openai("not json")):
        with pytest.raises(FoodVisionValidationError):
            await classify_food_image(b"imgbytes", None)


@pytest.mark.asyncio
async def test_negative_calories_rejected(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    with patch(
        "app.services.food_vision.AsyncOpenAI",
        return_value=_mock_openai(_food_json(calories=-50)),
    ):
        with pytest.raises(FoodVisionValidationError):
            await classify_food_image(b"imgbytes", None)


@pytest.mark.asyncio
async def test_api_error_raises(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=Exception("boom"))
    with patch("app.services.food_vision.AsyncOpenAI", return_value=client):
        with pytest.raises(FoodVisionError):
            await classify_food_image(b"imgbytes", None)


# --- extended food text schema (calories/macros) ---


def test_food_text_schema_accepts_nutrition():
    model = FoodStructuredJson.model_validate(
        {"description": "burger", "calories": 500, "protein_g": 25, "carbs_g": 40, "fat_g": 22}
    )
    assert model.calories == 500


def test_food_text_schema_rejects_negative():
    with pytest.raises(Exception):
        FoodStructuredJson.model_validate({"description": "x", "calories": -1})
