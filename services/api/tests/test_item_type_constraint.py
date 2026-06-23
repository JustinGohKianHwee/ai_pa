"""
Schema/code consistency guard (added after the Phase 18 'exercise' regression).

The classifier can emit any value in its ItemType literal, and the webhook writes that
value into inbox_items.item_type — which carries a CHECK constraint defined in the SQL
migrations. If the classifier gains a type that the constraint does not allow, every
capture of that type fails at the DB with a postgrest APIError (observed in Phase 18:
'exercise' classified fine but the inbox write was rejected).

These tests assert, without a database, that the latest item_type CHECK constraint in the
migrations permits every type the classifier can produce. DB-mocked unit tests cannot catch
a real constraint violation; this closes that gap by comparing the two sources directly.
"""
import re
from pathlib import Path
from typing import get_args

from app.services.classifier import ItemType

MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "supabase" / "migrations"


def _latest_allowed_item_types() -> set[str]:
    """Parse every `... item_type in ( '...', '...' )` block across all migrations and
    return the allowed set from the highest-numbered migration that defines one."""
    pattern = re.compile(r"item_type\s+in\s*\(([^)]*)\)", re.IGNORECASE)
    latest_file: Path | None = None
    latest_values: set[str] | None = None
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        text = path.read_text(encoding="utf-8")
        matches = pattern.findall(text)
        if not matches:
            continue
        # Use the last block in the file (a file may both drop+re-add).
        values = set(re.findall(r"'([^']+)'", matches[-1]))
        latest_file = path
        latest_values = values
    assert latest_values is not None, "no item_type CHECK constraint found in migrations"
    return latest_values


def test_classifier_types_are_all_allowed_by_db_constraint():
    classifier_types = set(get_args(ItemType))
    allowed = _latest_allowed_item_types()
    missing = classifier_types - allowed
    assert not missing, (
        f"classifier can emit item_type(s) {missing} that the inbox_items CHECK "
        f"constraint rejects; add them in a migration. Allowed: {sorted(allowed)}"
    )


def test_exercise_specifically_allowed():
    # Direct guard for the Phase 18 regression.
    assert "exercise" in _latest_allowed_item_types()
