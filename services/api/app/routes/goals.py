"""
Goals domain module (Phase 20) — read + minimal status toggle.

Confirmed goals are created by the atomic confirm_goal_item RPC (see review.py and
supabase/migrations/0015_habits_goals.sql). This router reads goals and toggles their
status (active/achieved/abandoned) — the only field mutable after confirmation, mirroring
the tasks.complete precedent. Goal content is edited in the inbox before confirmation, not
here. Status changes do not write memory_events.
"""
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from app.db.supabase_client import SupabaseConfigurationError, get_supabase_client
from app.security import require_user

router = APIRouter(tags=["goals"])

GoalStatus = Literal["active", "achieved", "abandoned"]

# source_table -> (display column, human label). Column may be null per row -> fall back to label.
LINK_SOURCES: dict[str, tuple[str, str]] = {
    "tasks": ("title", "Task"),
    "money_events": ("merchant", "Expense"),
    "food_logs": ("description", "Food"),
    "calendar_intents": ("title", "Calendar"),
    "exercise_logs": ("activity", "Exercise"),
    "habits": ("name", "Habit"),
    "decisions": ("decision", "Decision"),
    "notes": ("content", "Note"),
    "journal_entries": ("content", "Journal"),
    "lifestyle_checkins": ("mood", "Check-in"),
    "manual_financial_snapshots": ("as_of", "Snapshot"),
}
_LINK_TITLE_MAX = 80


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


class GoalResponse(BaseModel):
    id: str
    inbox_item_id: str
    title: str
    description: Optional[str] = None
    target: Optional[str] = None
    target_date: Optional[str] = None
    status: str
    target_value: Optional[float] = None
    target_currency: Optional[str] = None
    target_metric: Optional[str] = None
    created_at: str
    updated_at: str


class GoalsListResponse(BaseModel):
    items: list[GoalResponse]
    total: int


class GoalStatusUpdate(BaseModel):
    status: GoalStatus


class GoalLinkCreate(BaseModel):
    source_table: str
    source_id: str
    note: Optional[str] = None


class GoalLinkResponse(BaseModel):
    id: str
    goal_id: str
    source_table: str
    source_id: str
    note: Optional[str] = None
    created_at: str
    label: str
    title: Optional[str] = None


class GoalLinksListResponse(BaseModel):
    items: list[GoalLinkResponse]
    total: int


def _get_goal_or_404(client, goal_id: str, owner_id: str) -> dict:
    try:
        result = (
            client.table("goals")
            .select("*")
            .eq("owner_id", owner_id)
            .eq("id", goal_id)
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database query failed") from exc
    if not result.data:
        raise HTTPException(status_code=404, detail="Goal not found")
    return result.data[0]


def _resolve_link_title(client, source_table: str, source_id: str, owner_id: str) -> Optional[str]:
    column, _label = LINK_SOURCES[source_table]
    try:
        result = (
            client.table(source_table)
            .select(column)
            .eq("owner_id", owner_id)
            .eq("id", source_id)
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database query failed") from exc
    if not result.data:
        return None
    value = result.data[0].get(column)
    if value is None:
        return None
    title = str(value).strip()
    return title[:_LINK_TITLE_MAX] if title else None


def _source_record_exists(client, source_table: str, source_id: str, owner_id: str) -> bool:
    try:
        result = (
            client.table(source_table)
            .select("id")
            .eq("owner_id", owner_id)
            .eq("id", source_id)
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database query failed") from exc
    return bool(result.data)


def _link_response(client, row: dict, owner_id: str) -> GoalLinkResponse:
    _column, label = LINK_SOURCES[row["source_table"]]
    return GoalLinkResponse(
        id=row["id"],
        goal_id=row["goal_id"],
        source_table=row["source_table"],
        source_id=row["source_id"],
        note=row.get("note"),
        created_at=row["created_at"],
        label=label,
        title=_resolve_link_title(client, row["source_table"], row["source_id"], owner_id),
    )


def _existing_link(client, goal_id: str, source_table: str, source_id: str, owner_id: str) -> Optional[dict]:
    try:
        result = (
            client.table("goal_links")
            .select("*")
            .eq("owner_id", owner_id)
            .eq("goal_id", goal_id)
            .eq("source_table", source_table)
            .eq("source_id", source_id)
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database query failed") from exc
    return result.data[0] if result.data else None


@router.get("/goals")
def list_goals(owner_id: str = Depends(require_user)) -> GoalsListResponse:
    try:
        client = get_supabase_client()
    except SupabaseConfigurationError as exc:
        raise HTTPException(status_code=500, detail=f"Database configuration error: {exc}")

    try:
        result = (
            client.table("goals")
            .select("*")
            .eq("owner_id", owner_id)
            .order("created_at", desc=True)
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database query failed") from exc

    items = [GoalResponse(**row) for row in result.data]
    return GoalsListResponse(items=items, total=len(items))


@router.get("/goals/{goal_id}", response_model=GoalResponse)
def get_goal(goal_id: str, owner_id: str = Depends(require_user)) -> GoalResponse:
    try:
        client = get_supabase_client()
    except SupabaseConfigurationError as exc:
        raise HTTPException(status_code=500, detail=f"Database configuration error: {exc}")
    return GoalResponse(**_get_goal_or_404(client, goal_id, owner_id))


@router.patch("/goals/{goal_id}/status")
def update_goal_status(
    goal_id: str,
    body: GoalStatusUpdate,
    owner_id: str = Depends(require_user),
) -> GoalResponse:
    try:
        client = get_supabase_client()
    except SupabaseConfigurationError as exc:
        raise HTTPException(status_code=500, detail=f"Database configuration error: {exc}")

    try:
        result = (
            client.table("goals")
            .select("*")
            .eq("owner_id", owner_id)
            .eq("id", goal_id)
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database query failed") from exc

    if not result.data:
        raise HTTPException(status_code=404, detail="Goal not found")

    goal = result.data[0]

    # Idempotent: already in the requested status.
    if goal["status"] == body.status:
        return GoalResponse(**goal)

    try:
        updated = (
            client.table("goals")
            .update({"status": body.status, "updated_at": _now_utc()})
            .eq("owner_id", owner_id)
            .eq("id", goal_id)
            .eq("status", goal["status"])
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database update failed") from exc

    if not updated.data:
        # Concurrent status change — refetch to determine the outcome.
        try:
            refetch = (
                client.table("goals")
                .select("*")
                .eq("owner_id", owner_id)
                .eq("id", goal_id)
                .execute()
            )
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Database query failed") from exc

        if not refetch.data:
            raise HTTPException(status_code=404, detail="Goal not found")

        current = refetch.data[0]
        if current["status"] == body.status:
            return GoalResponse(**current)
        raise HTTPException(
            status_code=409, detail="Goal was modified concurrently; status update failed"
        )

    return GoalResponse(**updated.data[0])


@router.get("/goals/{goal_id}/links", response_model=GoalLinksListResponse)
def list_goal_links(goal_id: str, owner_id: str = Depends(require_user)) -> GoalLinksListResponse:
    try:
        client = get_supabase_client()
    except SupabaseConfigurationError as exc:
        raise HTTPException(status_code=500, detail=f"Database configuration error: {exc}")

    _get_goal_or_404(client, goal_id, owner_id)
    try:
        result = (
            client.table("goal_links")
            .select("*")
            .eq("owner_id", owner_id)
            .eq("goal_id", goal_id)
            .order("created_at", desc=True)
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database query failed") from exc

    items = [_link_response(client, row, owner_id) for row in result.data]
    return GoalLinksListResponse(items=items, total=len(items))


@router.post(
    "/goals/{goal_id}/links",
    response_model=GoalLinkResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_goal_link(
    goal_id: str,
    body: GoalLinkCreate,
    response: Response,
    owner_id: str = Depends(require_user),
) -> GoalLinkResponse:
    try:
        client = get_supabase_client()
    except SupabaseConfigurationError as exc:
        raise HTTPException(status_code=500, detail=f"Database configuration error: {exc}")

    # Required validation order: goal, source_table allow-list, source record, duplicate/insert.
    _get_goal_or_404(client, goal_id, owner_id)
    if body.source_table not in LINK_SOURCES:
        raise HTTPException(status_code=422, detail="unsupported source_table")
    if not _source_record_exists(client, body.source_table, body.source_id, owner_id):
        raise HTTPException(status_code=404, detail="linked record not found")

    existing = _existing_link(client, goal_id, body.source_table, body.source_id, owner_id)
    if existing is not None:
        response.status_code = status.HTTP_200_OK
        return _link_response(client, existing, owner_id)

    try:
        inserted = (
            client.table("goal_links")
            .insert({
                "goal_id": goal_id,
                "source_table": body.source_table,
                "source_id": body.source_id,
                "note": body.note,
            })
            .execute()
        )
    except Exception:
        # Possible race with another identical insert: preserve idempotency by re-selecting.
        existing = _existing_link(client, goal_id, body.source_table, body.source_id, owner_id)
        if existing is not None:
            response.status_code = status.HTTP_200_OK
            return _link_response(client, existing, owner_id)
        raise HTTPException(status_code=503, detail="Database insert failed")

    return _link_response(client, inserted.data[0], owner_id)


@router.delete("/goals/{goal_id}/links/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_goal_link(
    goal_id: str,
    link_id: str,
    owner_id: str = Depends(require_user),
) -> Response:
    try:
        client = get_supabase_client()
    except SupabaseConfigurationError as exc:
        raise HTTPException(status_code=500, detail=f"Database configuration error: {exc}")

    try:
        existing = (
            client.table("goal_links")
            .select("id")
            .eq("owner_id", owner_id)
            .eq("goal_id", goal_id)
            .eq("id", link_id)
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database query failed") from exc

    if not existing.data:
        raise HTTPException(status_code=404, detail="Goal link not found")

    try:
        (
            client.table("goal_links")
            .delete()
            .eq("owner_id", owner_id)
            .eq("goal_id", goal_id)
            .eq("id", link_id)
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database delete failed") from exc

    return Response(status_code=status.HTTP_204_NO_CONTENT)
