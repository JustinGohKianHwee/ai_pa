"""
Text classification service — assigns item_type and extracts structured data from
natural language captures using OpenAI gpt-4o-mini with JSON mode.

If OPENAI_API_KEY is absent, classify_text() returns a zero-confidence fallback so the
capture pipeline can continue without any AI dependency.

Exception hierarchy (raised only when the API key is present):
  ClassificationError          — OpenAI API call failed (network, quota, auth)
  ClassificationValidationError — API returned JSON that fails our Pydantic schema
"""

import json
import logging
import math
import os
from typing import Any, Literal, Optional

from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

logger = logging.getLogger(__name__)

CLASSIFICATION_MODEL = "gpt-4o-mini"

ItemType = Literal[
    "task", "finance", "calendar", "food", "exercise", "habit", "goal", "decision",
    "investment", "note", "journal", "unknown",
]

SYSTEM_PROMPT = """\
You are a personal-assistant classifier. Given a short natural-language message, classify \
it into exactly one type and extract structured data.

Allowed types and the EXACT fields to extract for each (no extra fields):
  task        – { "title": str|null, "due_date": str|null, "urgency": "today"|"this_week"|"someday"|null, "notes": str|null }
  finance     – { "amount": float, "currency": "SGD" (default), "direction": "expense"|"income", "merchant": str|null, "category": str|null, "occurred_at": str|null, "notes": str|null }
  calendar    – { "title": str, "proposed_datetime": str|null, "location": str|null, "notes": str|null }
  food        – { "description": str, "meal_type": "breakfast"|"lunch"|"dinner"|"snack"|null, "logged_at": str|null, "calories": float|null, "protein_g": float|null, "carbs_g": float|null, "fat_g": float|null }  (estimate calories and macros from the description; approximate is fine)
  exercise    – { "activity": str, "duration_min": float|null, "distance_km": float|null, "sets": int|null, "reps": int|null, "intensity": str|null, "calories": float|null, "logged_at": str|null, "notes": str|null }  (extract the fields present; estimate calories burned roughly if you can — approximate is fine)
  habit       – { "name": str, "cadence": str|null, "target": str|null, "notes": str|null }  (cadence is free text like "daily" or "3x a week"; do not invent one)
  goal        – { "title": str, "description": str|null, "target": str|null, "target_date": str|null, "notes": str|null }  (target/target_date are free text; if no date is given, target_date is null — do not invent one)
  decision    – { "decision": str, "reason": str|null, "options_considered": str|null, "expected_outcome": str|null, "confidence": float|null, "category": str|null, "decided_at": str|null, "notes": str|null }  (decision = the choice made; confidence is the user's 0.0-1.0 confidence ONLY if they state it; do not invent confidence or decided_at)
  investment  – { "action_intent": "buy"|"sell"|"note", "ticker": str|null, "amount": float|null, "currency": "SGD" (default), "notes": str|null }
  note        – { "content": str, "tags": [str] }
  journal     – { "content": str, "mood": str|null }
  unknown     – {}

Disambiguation rules (apply before choosing a type):
  - Physical activity or workouts — running, jogging, walking, steps, gym, weights/lifting, \
swimming, cycling, hiking, yoga, pilates, sports, a race — are ALWAYS "exercise", never "food". \
"5k run", "ran 5k in 28 min", "did legs at the gym", "1h yoga" are exercise.
  - "food" is ONLY for eating or drinking something. Calories EATEN → food; calories BURNED \
through activity → exercise.
  - A "habit" is a RECURRING intended behaviour ("meditate every morning", "gym 3x a week", \
"drink 2L of water daily" — cues: every / daily / weekly / each / routine / habit). A one-off \
thing to do is a "task", NOT a habit.
  - A "goal" is a desired OUTCOME or target over time, often with a target and/or deadline \
("save $50k for the BTO downpayment", "reach 100k portfolio by end 2027", "read 24 books this \
year"). A single action is a "task"; a passing thought or preference is a "note".
  - A "decision" records a CHOICE between alternatives, usually with a reason. Strong cues: \
"choose / chose / choosing / decide / decided / going with / opting for / picking X (instead of / \
over / rather than) Y", or any statement that weighs options and commits to one. \
Example: "Choose term insurance instead of whole life for pure protection" → decision (NOT note). \
"X instead of Y" or "X over Y" is ALWAYS a decision. Distinguish from: a "goal" (a future \
outcome/target to achieve), a "task" (a single action to perform), and a "note" (an observation, \
fact, or preference with NO choice between alternatives). Only fall back to "note"/"unknown" when \
there is genuinely no choice being made — do not fabricate a decision, but do not downgrade a clear \
choice to a note either.
  - Do not invent a logged_at timestamp, a goal target_date, or a decision decided_at/confidence. \
If not explicitly given, set them to null.

Respond ONLY with valid JSON in this exact shape — no extra commentary:
{
  "item_type": "<one of the types above>",
  "title": "<short human-readable title, max 100 chars>",
  "body": "<the original text or a cleaned version>",
  "structured_json": { <fields for the chosen type — no extra keys> },
  "confidence": <float 0.0–1.0>
}"""


# ---------------------------------------------------------------------------
# Per-type structured_json schemas
# ---------------------------------------------------------------------------
# extra="forbid" ensures obsolete or misspelled fields fail validation and
# surface as ClassificationValidationError rather than being silently accepted.
# Design note: for tasks, inbox_items.title is canonical; structured_json.task.title
# is informational only and Phase 8 will use inbox_items.title for the tasks row.

class TaskStructuredJson(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Optional[str] = None
    due_date: Optional[str] = None
    urgency: Optional[Literal["today", "this_week", "someday"]] = None
    notes: Optional[str] = None


class FinanceStructuredJson(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount: float
    currency: str = "SGD"
    direction: Literal["expense", "income"]
    merchant: Optional[str] = None
    category: Optional[str] = None
    occurred_at: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("amount")
    @classmethod
    def amount_must_be_finite_and_positive(cls, v: float) -> float:
        if not math.isfinite(v) or v <= 0:
            raise ValueError("amount must be a finite number greater than zero")
        return v


class CalendarStructuredJson(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    proposed_datetime: Optional[str] = None
    location: Optional[str] = None
    notes: Optional[str] = None


class FoodStructuredJson(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str
    meal_type: Optional[Literal["breakfast", "lunch", "dinner", "snack"]] = None
    logged_at: Optional[str] = None
    calories: Optional[float] = None
    protein_g: Optional[float] = None
    carbs_g: Optional[float] = None
    fat_g: Optional[float] = None

    @field_validator("calories", "protein_g", "carbs_g", "fat_g")
    @classmethod
    def nutrition_finite_nonneg(cls, v: Optional[float]) -> Optional[float]:
        if v is None:
            return v
        if not math.isfinite(v) or v < 0:
            raise ValueError("nutrition values must be finite and non-negative")
        return v


class ExerciseStructuredJson(BaseModel):
    model_config = ConfigDict(extra="forbid")
    activity: str
    duration_min: Optional[float] = None
    distance_km: Optional[float] = None
    sets: Optional[int] = None
    reps: Optional[int] = None
    intensity: Optional[str] = None
    calories: Optional[float] = None
    logged_at: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("duration_min", "distance_km", "calories")
    @classmethod
    def metric_finite_nonneg(cls, v: Optional[float]) -> Optional[float]:
        if v is None:
            return v
        if not math.isfinite(v) or v < 0:
            raise ValueError("exercise metrics must be finite and non-negative")
        return v

    @field_validator("sets", "reps")
    @classmethod
    def count_nonneg(cls, v: Optional[int]) -> Optional[int]:
        if v is None:
            return v
        if v < 0:
            raise ValueError("sets/reps must be non-negative")
        return v


class HabitStructuredJson(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    cadence: Optional[str] = None
    target: Optional[str] = None
    notes: Optional[str] = None


class GoalStructuredJson(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    description: Optional[str] = None
    target: Optional[str] = None
    target_date: Optional[str] = None
    notes: Optional[str] = None


class DecisionStructuredJson(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: str
    reason: Optional[str] = None
    options_considered: Optional[str] = None
    expected_outcome: Optional[str] = None
    confidence: Optional[float] = None
    category: Optional[str] = None
    decided_at: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("confidence")
    @classmethod
    def confidence_in_range(cls, v: Optional[float]) -> Optional[float]:
        if v is None:
            return v
        if not math.isfinite(v) or not (0.0 <= v <= 1.0):
            raise ValueError("confidence must be a finite number between 0.0 and 1.0")
        return v


class InvestmentStructuredJson(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action_intent: Literal["buy", "sell", "note"]
    ticker: Optional[str] = None
    amount: Optional[float] = None
    currency: str = "SGD"
    notes: Optional[str] = None


class JournalStructuredJson(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str
    mood: Optional[str] = None


class NoteStructuredJson(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str
    tags: list[str] = Field(default_factory=list)


class UnknownStructuredJson(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # No fields — structured_json must be {} for unknown items


_ITEM_TYPE_SCHEMAS: dict[str, type[BaseModel]] = {
    "task":       TaskStructuredJson,
    "finance":    FinanceStructuredJson,
    "calendar":   CalendarStructuredJson,
    "food":       FoodStructuredJson,
    "exercise":   ExerciseStructuredJson,
    "habit":      HabitStructuredJson,
    "goal":       GoalStructuredJson,
    "decision":   DecisionStructuredJson,
    "investment": InvestmentStructuredJson,
    "journal":    JournalStructuredJson,
    "note":       NoteStructuredJson,
    "unknown":    UnknownStructuredJson,
}


# ---------------------------------------------------------------------------
# Classification result model
# ---------------------------------------------------------------------------

class ClassificationResult(BaseModel):
    item_type: ItemType
    title: str
    body: str
    structured_json: dict[str, Any]
    confidence: float

    @field_validator("title")
    @classmethod
    def truncate_title(cls, v: str) -> str:
        return v[:100]

    @field_validator("confidence")
    @classmethod
    def validate_confidence_range(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError(f"confidence must be 0.0–1.0, got {v}")
        return v

    @model_validator(mode="after")
    def validate_structured_json_shape(self) -> "ClassificationResult":
        schema = _ITEM_TYPE_SCHEMAS.get(self.item_type)
        if schema is not None:
            try:
                validated = schema.model_validate(self.structured_json)
                # Store the normalized output so defaults (e.g. currency="SGD") are
                # persisted and None values for omitted optional fields are dropped.
                self.structured_json = validated.model_dump(exclude_none=True)
            except ValidationError as exc:
                raise ValueError(
                    f"structured_json invalid for item_type '{self.item_type}': {exc}"
                ) from exc
        return self


class ClassificationError(Exception):
    """The OpenAI API call failed (network, quota, auth, etc.)."""


class ClassificationValidationError(Exception):
    """The API returned output that does not match ClassificationResult's schema."""


def _fallback_result(text: str) -> ClassificationResult:
    return ClassificationResult(
        item_type="unknown",
        title=text[:100],
        body=text,
        structured_json={},
        confidence=0.0,
    )


async def classify_text(text: str) -> ClassificationResult:
    """
    Classify *text* using OpenAI.

    Returns a ClassificationResult. If OPENAI_API_KEY is not set, returns a fallback
    result (item_type="unknown", confidence=0.0) without making any network call.

    Raises ClassificationError if the API call fails.
    Raises ClassificationValidationError if the response cannot be parsed or validated.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.debug("OPENAI_API_KEY not set; returning fallback classification")
        return _fallback_result(text)

    try:
        client = AsyncOpenAI(api_key=api_key, timeout=30.0)
        response = await client.chat.completions.create(
            model=CLASSIFICATION_MODEL,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            temperature=0.1,
        )
        raw = response.choices[0].message.content or ""
    except Exception as exc:
        logger.warning("OpenAI API call failed: %s", type(exc).__name__)
        raise ClassificationError(f"API call failed: {type(exc).__name__}") from exc

    try:
        data = json.loads(raw)
        return ClassificationResult.model_validate(data)
    except (json.JSONDecodeError, ValidationError) as exc:
        logger.warning("Classifier output failed validation: %s", exc)
        raise ClassificationValidationError(f"Invalid classifier output: {exc}") from exc
