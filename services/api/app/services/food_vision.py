"""
Food photo vision service (Phase 17) — estimates a dish + calories/macros from an image
using OpenAI gpt-4o-mini (image input), mirroring the text classifier's structure.

If OPENAI_API_KEY is absent, returns a non-food fallback so the capture goes to manual review
rather than fabricating a meal.

Exception hierarchy (raised only when the API key is present):
  FoodVisionError           — OpenAI API call failed (network, quota, auth)
  FoodVisionValidationError — API returned JSON that fails the schema
"""
import base64
import json
import logging
import math
import os
from typing import Literal, Optional

from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

logger = logging.getLogger(__name__)

FOOD_VISION_MODEL = "gpt-4o-mini"

SYSTEM_PROMPT = """\
You analyse a single photo and decide whether it shows food/drink. If it does, identify the \
dish and estimate its nutrition for the portion shown. Estimates are approximate — the user \
will review and correct them.

If the user provides a caption, treat it as AUTHORITATIVE context that overrides your visual \
guess: it may name the dish, list ingredients, specify the portion size, or note details the \
photo cannot show (e.g. "half portion", "no rice", "cooked in butter", "oat milk not dairy"). \
Use it to disambiguate the image and to scale the nutrition estimate. If the caption clearly \
describes food, set "is_food": true even when the image is ambiguous.

Respond ONLY with valid JSON in this exact shape — no commentary:
{
  "is_food": true|false,
  "description": "<short description of the dish, or '' if not food>",
  "meal_type": "breakfast"|"lunch"|"dinner"|"snack"|null,
  "calories": <number|null>,
  "protein_g": <number|null>,
  "carbs_g": <number|null>,
  "fat_g": <number|null>,
  "confidence": <float 0.0-1.0>
}
If the image is not food/drink, set "is_food": false and leave nutrition fields null."""


class FoodVisionResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    is_food: bool
    description: str = ""
    meal_type: Optional[Literal["breakfast", "lunch", "dinner", "snack"]] = None
    calories: Optional[float] = None
    protein_g: Optional[float] = None
    carbs_g: Optional[float] = None
    fat_g: Optional[float] = None
    confidence: float = 0.0

    @field_validator("calories", "protein_g", "carbs_g", "fat_g")
    @classmethod
    def nutrition_finite_nonneg(cls, v: Optional[float]) -> Optional[float]:
        if v is None:
            return v
        if not math.isfinite(v) or v < 0:
            raise ValueError("nutrition values must be finite and non-negative")
        return v

    @field_validator("confidence")
    @classmethod
    def clamp_confidence(cls, v: float) -> float:
        if not math.isfinite(v):
            return 0.0
        return max(0.0, min(1.0, v))


class FoodVisionError(Exception):
    """The OpenAI API call failed (network, quota, auth, etc.)."""


class FoodVisionValidationError(Exception):
    """The API returned output that does not match FoodVisionResult's schema."""


async def classify_food_image(
    image_bytes: bytes, caption: Optional[str] = None
) -> FoodVisionResult:
    """
    Estimate food + nutrition from a photo. If OPENAI_API_KEY is unset, returns a non-food
    fallback (so the item goes to manual review). Raises FoodVisionError / FoodVisionValidationError
    when a key is present and the call or output fails.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.debug("OPENAI_API_KEY not set; food image treated as non-food fallback")
        return FoodVisionResult(is_food=False, description="", confidence=0.0)

    b64 = base64.b64encode(image_bytes).decode("ascii")
    data_url = f"data:image/jpeg;base64,{b64}"
    user_text = "Identify the food and estimate its nutrition for the portion shown."
    clean_caption = (caption or "").strip()
    if clean_caption:
        # Frame the caption as authoritative context rather than dumping it raw, so the
        # model weights it over a pure visual guess (e.g. portion size, hidden ingredients).
        user_text += (
            "\n\nThe user added this caption describing the food — treat it as authoritative "
            f'context for the dish, ingredients, and portion:\n"{clean_caption}"'
        )

    try:
        oai = AsyncOpenAI(api_key=api_key, timeout=60.0)
        response = await oai.chat.completions.create(
            model=FOOD_VISION_MODEL,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_text},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                },
            ],
            temperature=0.1,
        )
        raw = response.choices[0].message.content or ""
    except Exception as exc:
        logger.warning("Food vision API call failed: %s", type(exc).__name__)
        raise FoodVisionError(f"API call failed: {type(exc).__name__}") from exc

    try:
        data = json.loads(raw)
        return FoodVisionResult.model_validate(data)
    except (json.JSONDecodeError, ValidationError) as exc:
        logger.warning("Food vision output failed validation: %s", exc)
        raise FoodVisionValidationError(f"Invalid food vision output: {exc}") from exc
