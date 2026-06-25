"""
Shared expense-category taxonomy (Phase 22d-2 fix).

A small FIXED set of categories so the "by category" summary (Phase 22c) stays coherent — free-form
labels ("Food" vs "Dining" vs "Food & Drink") fragment the grouping. Every path that proposes a
category (the text classifier, statement PDF extraction, statement CSV column) normalizes to this
set; anything unrecognised becomes None → shown as "uncategorized" until the user edits it.

The user can always override the proposed category in the inbox before confirming, so this is a
review-first suggestion, not an authoritative label.
"""
from typing import Optional

EXPENSE_CATEGORIES: list[str] = [
    "Food & Drink",
    "Groceries",
    "Transport",
    "Shopping",
    "Bills & Utilities",
    "Entertainment",
    "Health",
    "Travel",
    "Education",
    "Fees & Charges",
    "Other",
]

# Lower-cased lookup for case-insensitive normalization.
_CANONICAL = {c.lower(): c for c in EXPENSE_CATEGORIES}


def normalize_category(value: Optional[str]) -> Optional[str]:
    """Map a raw category string to a canonical EXPENSE_CATEGORIES value, else None.

    Case-insensitive exact match. Unknown/blank → None (so it surfaces as uncategorized rather than
    inventing a label the summary can't group).
    """
    if not value:
        return None
    return _CANONICAL.get(value.strip().lower())
