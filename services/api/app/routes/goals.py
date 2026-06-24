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

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.db.supabase_client import SupabaseConfigurationError, get_supabase_client
from app.security import require_user

router = APIRouter(tags=["goals"])

GoalStatus = Literal["active", "achieved", "abandoned"]


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


@router.get("/goals", dependencies=[Depends(require_user)])
def list_goals() -> GoalsListResponse:
    try:
        client = get_supabase_client()
    except SupabaseConfigurationError as exc:
        raise HTTPException(status_code=500, detail=f"Database configuration error: {exc}")

    try:
        result = (
            client.table("goals")
            .select("*")
            .order("created_at", desc=True)
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database query failed") from exc

    items = [GoalResponse(**row) for row in result.data]
    return GoalsListResponse(items=items, total=len(items))


@router.patch("/goals/{goal_id}/status", dependencies=[Depends(require_user)])
def update_goal_status(goal_id: str, body: GoalStatusUpdate) -> GoalResponse:
    try:
        client = get_supabase_client()
    except SupabaseConfigurationError as exc:
        raise HTTPException(status_code=500, detail=f"Database configuration error: {exc}")

    try:
        result = client.table("goals").select("*").eq("id", goal_id).execute()
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
            .eq("id", goal_id)
            .eq("status", goal["status"])
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database update failed") from exc

    if not updated.data:
        # Concurrent status change — refetch to determine the outcome.
        try:
            refetch = client.table("goals").select("*").eq("id", goal_id).execute()
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
