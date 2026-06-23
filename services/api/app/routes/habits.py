"""
Habits domain module (Phase 20) — read only.

Confirmed habits are created by the atomic confirm_habit_item RPC (see review.py and
supabase/migrations/0015_habits_goals.sql). This router only reads habits. Habits are
definition-only in Phase 20 — no check-ins, streaks, or post-confirm mutation.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from app.db.supabase_client import SupabaseConfigurationError, get_supabase_client
from app.security import require_user

router = APIRouter(tags=["habits"])


class HabitResponse(BaseModel):
    id: str
    inbox_item_id: str
    name: str
    cadence: Optional[str] = None
    target: Optional[str] = None
    notes: Optional[str] = None
    created_at: str


class HabitsListResponse(BaseModel):
    items: list[HabitResponse]
    total: int


@router.get("/habits", dependencies=[Depends(require_user)])
def list_habits() -> HabitsListResponse:
    try:
        client = get_supabase_client()
    except SupabaseConfigurationError as exc:
        raise HTTPException(status_code=500, detail=f"Database configuration error: {exc}")

    try:
        result = (
            client.table("habits")
            .select("*")
            .order("created_at", desc=True)
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database query failed") from exc

    items = [HabitResponse(**row) for row in result.data]
    return HabitsListResponse(items=items, total=len(items))
