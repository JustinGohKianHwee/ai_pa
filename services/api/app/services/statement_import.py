"""
Statement CSV parsing (Phase 22d) — pure, testable, no DB.

Expected CSV header (case-insensitive): date, description, amount[, currency].
Only positive expense amounts are kept (statements list spend). `currency` per row, else the
caller-supplied default. Malformed input raises StatementParseError rather than guessing.
"""
import csv
import io
import math
from decimal import Decimal, InvalidOperation
from typing import Optional


class StatementParseError(Exception):
    """The uploaded statement could not be parsed into valid rows."""


def _clean_amount(raw: str) -> Optional[float]:
    s = (raw or "").strip().replace(",", "").replace("$", "")
    if not s:
        return None
    try:
        val = float(Decimal(s))
    except (InvalidOperation, ValueError):
        return None
    if not math.isfinite(val) or val <= 0:
        return None
    return round(val, 2)


def parse_statement_csv(content: str, default_currency: str) -> list[dict]:
    """Parse CSV text → [{occurred_on, description, amount, currency}, ...].

    Raises StatementParseError if the header lacks required columns or no valid expense rows
    are found. Rows with a non-positive/unparseable amount are skipped.
    """
    default_currency = (default_currency or "").strip().upper()
    try:
        reader = csv.DictReader(io.StringIO(content))
    except csv.Error as exc:
        raise StatementParseError(f"Could not read CSV: {exc}") from exc

    if reader.fieldnames is None:
        raise StatementParseError("Empty file or missing header row")

    cols = {(name or "").strip().lower(): name for name in reader.fieldnames}
    if "amount" not in cols:
        raise StatementParseError("CSV must have an 'amount' column")
    if "description" not in cols and "date" not in cols:
        raise StatementParseError("CSV must have a 'description' or 'date' column")

    rows: list[dict] = []
    for raw in reader:
        amount = _clean_amount(raw.get(cols["amount"], ""))
        if amount is None:
            continue  # skip non-expense / unparseable rows
        ccy = (raw.get(cols["currency"], "").strip().upper() if "currency" in cols else "") or default_currency
        if not ccy:
            raise StatementParseError("No currency column and no default currency supplied")
        rows.append(
            {
                "occurred_on": (raw.get(cols["date"], "").strip() if "date" in cols else None) or None,
                "description": (raw.get(cols["description"], "").strip() if "description" in cols else "") or None,
                "amount": amount,
                "currency": ccy,
            }
        )

    if not rows:
        raise StatementParseError("No valid expense rows found in the statement")
    return rows
