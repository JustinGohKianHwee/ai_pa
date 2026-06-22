"""
Account-reference masking.

Full broker account numbers must never appear in API responses or logs. `mask_account`
keeps only the last few characters so the user can still tell accounts apart. An optional
friendly label (from env) takes precedence when provided.
"""
from typing import Optional


def mask_account(raw: Optional[str], label: Optional[str] = None) -> str:
    """
    Return a safe, stable reference for an account.

    - If `label` is a non-empty string, use it verbatim (user-chosen friendly name).
    - Otherwise mask `raw`, keeping the last 4 characters: "U1234567" -> "U***4567".
    - Short or missing values degrade safely without leaking the full value.
    """
    if label:
        label = label.strip()
        if label:
            return label

    if not raw:
        return "unknown"

    raw = str(raw).strip()
    if not raw:
        return "unknown"

    if len(raw) <= 4:
        # Too short to keep 4 and still mask; redact entirely.
        return "*" * len(raw)

    return f"{raw[0]}***{raw[-4:]}"
