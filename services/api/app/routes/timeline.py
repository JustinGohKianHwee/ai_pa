"""
Daily Life Timeline (Phase 19) — read only.

A chronological, filterable feed across all confirmed domains plus portfolio snapshots,
read entirely from `memory_events` (the append-only log written by the confirmation and
snapshot RPCs since Phase 15b). No domain-table joins: every row's `payload_json` already
carries the display fields. No writes, no AI, no pipeline involvement.

Scope note: `memory_events` only contains confirmations + snapshot_created events written
from Phase 15b onward. Captures, pending, and rejected items are NOT in the timeline, and
records confirmed before 15b are not backfilled.

Pagination is keyset (cursor) on (occurred_at desc, id desc): we fetch limit+1 rows; if more
than `limit` come back there is another page and `next_cursor` encodes the last kept row.
"""
import base64
import binascii
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.db.supabase_client import SupabaseConfigurationError, get_supabase_client
from app.security import require_user

router = APIRouter(tags=["timeline"])

# Domains the timeline understands (matches memory_events.domain written by the RPCs).
ALLOWED_DOMAINS = {
    "task", "money", "food", "calendar", "exercise", "habit", "goal", "decision",
    "portfolio_snapshot",
}

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


class TimelineEntry(BaseModel):
    id: str
    occurred_at: str
    domain: str
    event_type: str
    source_table: Optional[str] = None
    source_id: Optional[str] = None
    payload: dict


class TimelineResponse(BaseModel):
    items: list[TimelineEntry]
    next_cursor: Optional[str] = None


def _parse_iso(value: str, field: str) -> str:
    """Validate an ISO-8601 timestamp; return a normalized ISO string. 422 on failure."""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(
            status_code=422, detail=f"{field} must be an ISO-8601 timestamp"
        )
    return parsed.isoformat()


def _parse_domains(domains: Optional[str]) -> Optional[list[str]]:
    if domains is None:
        return None
    requested = [d.strip() for d in domains.split(",") if d.strip()]
    if not requested:
        return None
    invalid = [d for d in requested if d not in ALLOWED_DOMAINS]
    if invalid:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown domain(s): {invalid}. Allowed: {sorted(ALLOWED_DOMAINS)}",
        )
    # De-duplicate while preserving order.
    return list(dict.fromkeys(requested))


def _encode_cursor(occurred_at: str, row_id: str) -> str:
    return base64.urlsafe_b64encode(f"{occurred_at}|{row_id}".encode()).decode()


def _decode_cursor(cursor: str) -> tuple[str, str]:
    """Decode an opaque keyset cursor into (occurred_at, id). 422 on malformed input."""
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
    except (binascii.Error, ValueError, UnicodeDecodeError):
        raise HTTPException(status_code=422, detail="Malformed cursor")
    if "|" not in raw:
        raise HTTPException(status_code=422, detail="Malformed cursor")
    occurred_at, _, row_id = raw.partition("|")
    if not occurred_at or not row_id:
        raise HTTPException(status_code=422, detail="Malformed cursor")
    return occurred_at, row_id


@router.get("/timeline", dependencies=[Depends(require_user)])
def get_timeline(
    domains: Optional[str] = None,
    from_: Optional[str] = Query(default=None, alias="from"),
    to: Optional[str] = None,
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    cursor: Optional[str] = None,
) -> TimelineResponse:
    domain_list = _parse_domains(domains)
    from_iso = _parse_iso(from_, "from") if from_ is not None else None
    to_iso = _parse_iso(to, "to") if to is not None else None
    cursor_parts = _decode_cursor(cursor) if cursor is not None else None

    try:
        client = get_supabase_client()
    except SupabaseConfigurationError as exc:
        raise HTTPException(status_code=500, detail=f"Database configuration error: {exc}")

    try:
        query = (
            client.table("memory_events")
            .select("id, occurred_at, domain, event_type, source_table, source_id, payload_json")
            .order("occurred_at", desc=True)
            .order("id", desc=True)
        )
        if domain_list is not None:
            query = query.in_("domain", domain_list)
        if from_iso is not None:
            query = query.gte("occurred_at", from_iso)
        if to_iso is not None:
            query = query.lt("occurred_at", to_iso)
        if cursor_parts is not None:
            c_ts, c_id = cursor_parts
            # Exact keyset: rows strictly before the cursor in (occurred_at, id) order.
            query = query.or_(
                f"occurred_at.lt.{c_ts},and(occurred_at.eq.{c_ts},id.lt.{c_id})"
            )
        # Fetch one extra row to detect whether a further page exists.
        result = query.limit(limit + 1).execute()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database query failed") from exc

    rows = result.data or []
    has_more = len(rows) > limit
    page = rows[:limit]

    items = [
        TimelineEntry(
            id=row["id"],
            occurred_at=row["occurred_at"],
            domain=row["domain"],
            event_type=row["event_type"],
            source_table=row.get("source_table"),
            source_id=row.get("source_id"),
            payload=row.get("payload_json") or {},
        )
        for row in page
    ]

    next_cursor = None
    if has_more and page:
        last = page[-1]
        next_cursor = _encode_cursor(last["occurred_at"], last["id"])

    return TimelineResponse(items=items, next_cursor=next_cursor)
