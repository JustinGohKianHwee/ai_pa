"""
PDF statement extraction (Phase 22d-2) — text-based bank/card statements.

Two steps, both pure of any DB:
  1. extract_pdf_text(pdf_bytes)            — pypdf text extraction (deterministic).
  2. extract_rows_from_text(text, default)  — gpt-4o-mini structures the text into expense rows
                                              (same shape as parse_statement_csv).

The LLM only PROPOSES rows. Every extracted row is staged and becomes a pending finance
inbox_item that the user reviews and confirms before it becomes a money_event — so an extraction
error is caught in the inbox, never auto-trusted. This does not violate the deterministic-finance
rule: that rule governs COMPUTING numbers (summaries/net worth via SQL), not parsing a document.

Unlike food vision, a missing OPENAI_API_KEY raises rather than silently returning no rows — a
silent "0 rows imported" would look like a successful import. CSV import stays key-free.

Exceptions:
  StatementParseError      — reused from statement_import; raised when the PDF has no text layer
                             (e.g. a scanned image) so the user gets a clear message.
  StatementExtractionError — the OpenAI call failed or returned output failing the schema, or no
                             API key is configured.
"""
import io
import json
import logging
import math
import os
from typing import Optional

from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from app.services.expense_categories import EXPENSE_CATEGORIES, normalize_category
from app.services.statement_import import StatementParseError

logger = logging.getLogger(__name__)

STATEMENT_EXTRACTION_MODEL = "gpt-4o-mini"

# Guardrails: a statement can be long, but feeding an unbounded blob to the model is wasteful and
# risky. Truncate to a generous bound (text-based statements are small once extracted).
MAX_TEXT_CHARS = 60_000

SYSTEM_PROMPT = """\
You read the raw text of a bank or credit-card statement and extract every EXPENSE/DEBIT line \
item as a structured transaction. The user will review and correct every row before it is saved, \
so extract faithfully, never invent rows, and prefer leaving a field null over guessing.

Rules:
  - Extract ONLY money the user SPENT (debits, purchases, charges, withdrawals).
  - SKIP credits, refunds, incoming payments, repayments, interest received, opening/closing \
balances, running balances, subtotals, totals, and summary lines.
  - amount is the POSITIVE spend amount as a number (no currency symbols, no thousands commas).
  - currency is the statement's currency code if shown (e.g. SGD, USD); otherwise use the default.
  - occurred_on is the transaction date as printed (free text, e.g. "2026-06-01" or "01 Jun"); \
null if absent.
  - raw_descriptor is the line's descriptor text copied EXACTLY as printed (verbatim, including \
codes like "GRAB* GPC-A-9A8QF2CWW4 SI SGP 06MAY"). Do not clean, expand, or abbreviate it.
  - merchant is a clean brand/merchant name ONLY when you clearly recognise it (e.g. "Grab", \
"Starbucks", "Shopee"); otherwise null. Do not guess a merchant from an opaque code.
  - category must be EXACTLY one of this list, and ONLY when the merchant/description CLEARLY \
implies it: {categories}. Otherwise null.
      * Do NOT infer category from reference or transaction codes (e.g. "GPC-...", auth/approval \
numbers, alphanumeric IDs) — those identify the payment, not what was bought.
      * For super-app / aggregator merchants whose specific service is NOT clear from the line \
(e.g. Grab — could be a ride OR food delivery — Shopee, GoPay, PayLah), set merchant to the brand \
and leave category null for the user to decide.
  - Do NOT merge or split lines. Do NOT estimate or fabricate amounts you cannot read.

Respond ONLY with valid JSON in this exact shape — no commentary:
{{
  "rows": [
    {{ "occurred_on": str|null, "raw_descriptor": str, "merchant": str|null, "amount": <number>, "currency": str, "category": str|null }}
  ]
}}
If you find no expense lines, return {{"rows": []}}.""".format(
    categories=", ".join(EXPENSE_CATEGORIES)
)


class _ExtractedRow(BaseModel):
    model_config = ConfigDict(extra="ignore")
    occurred_on: Optional[str] = None
    raw_descriptor: str = ""
    merchant: Optional[str] = None
    amount: float
    currency: str = ""
    category: Optional[str] = None

    @field_validator("category")
    @classmethod
    def coerce_category(cls, v: Optional[str]) -> Optional[str]:
        # Snap to the fixed taxonomy; unknown labels become None (uncategorized), reviewable later.
        # Ambiguous rows (e.g. Grab) are expected to arrive as null and stay null until reviewed.
        return normalize_category(v)

    @field_validator("amount")
    @classmethod
    def amount_finite_positive(cls, v: float) -> float:
        if not math.isfinite(v) or v <= 0:
            raise ValueError("amount must be finite and positive")
        return round(v, 2)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, v: str) -> str:
        # Blank is allowed here — the caller falls back to the default currency. Rows with neither
        # an explicit nor a default currency are dropped (never guessed) in extract_rows_from_text.
        return (v or "").strip().upper()


class _Extraction(BaseModel):
    model_config = ConfigDict(extra="ignore")
    rows: list[_ExtractedRow] = []


class StatementExtractionError(Exception):
    """PDF row extraction failed (no API key, API error, or invalid model output)."""


def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract concatenated text from a text-based PDF.

    Raises StatementParseError if the PDF cannot be read or has no extractable text layer
    (typically a scanned image), so the caller can tell the user it looks scanned.
    """
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(pdf_bytes))
        parts = [(page.extract_text() or "") for page in reader.pages]
    except StatementParseError:
        raise
    except Exception as exc:  # malformed/encrypted PDF, etc.
        raise StatementParseError(f"Could not read PDF: {type(exc).__name__}") from exc

    text = "\n".join(parts).strip()
    if not text:
        raise StatementParseError(
            "No text could be extracted from this PDF. It may be a scanned image — "
            "please upload a text-based PDF or a CSV export."
        )
    return text[:MAX_TEXT_CHARS]


async def extract_rows_from_text(text: str, default_currency: str) -> list[dict]:
    """Structure statement text into expense rows via gpt-4o-mini.

    Returns the same shape as parse_statement_csv:
    [{occurred_on, raw_descriptor, merchant, amount, currency, category}]. raw_descriptor is the
    verbatim bank line; merchant/category may be None when the line is ambiguous (left for review).
    Raises StatementExtractionError if no API key is configured, the API call fails, or the
    output fails validation.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise StatementExtractionError(
            "PDF statement import requires OPENAI_API_KEY to be configured. "
            "Use a CSV export instead, or set the key."
        )

    default_ccy = (default_currency or "").strip().upper()
    user_text = (
        f"Default currency (use when a row has no explicit currency): {default_ccy or 'SGD'}\n\n"
        "Statement text follows:\n\n" + text
    )

    try:
        oai = AsyncOpenAI(api_key=api_key, timeout=90.0)
        response = await oai.chat.completions.create(
            model=STATEMENT_EXTRACTION_MODEL,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_text},
            ],
            temperature=0.0,
        )
        raw = response.choices[0].message.content or ""
    except Exception as exc:
        logger.warning("Statement extraction API call failed: %s", type(exc).__name__)
        raise StatementExtractionError(f"API call failed: {type(exc).__name__}") from exc

    try:
        data = json.loads(raw)
        extraction = _Extraction.model_validate(data)
    except (json.JSONDecodeError, ValidationError) as exc:
        logger.warning("Statement extraction output failed validation: %s", exc)
        raise StatementExtractionError(f"Invalid extraction output: {exc}") from exc

    rows: list[dict] = []
    for r in extraction.rows:
        ccy = r.currency or default_ccy
        if not ccy:
            continue  # no currency anywhere — drop rather than guess
        raw_descriptor = (r.raw_descriptor or "").strip()
        rows.append(
            {
                "occurred_on": (r.occurred_on or "").strip() or None,
                "raw_descriptor": raw_descriptor or None,
                "merchant": (r.merchant or "").strip() or None,
                "amount": r.amount,
                "currency": ccy,
                "category": r.category,
            }
        )
    return rows
