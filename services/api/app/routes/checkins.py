"""
Lifestyle check-ins domain module (Phase 23b) — read-only list.

Confirmed check-ins are created by the atomic confirm_checkin_item RPC (see review.py and
supabase/migrations/0021_lifestyle_checkins.sql). This router lists them newest-first. Fields are
edited in the inbox before confirmation, not here; entries are immutable after confirmation.

This is a personal reflective log, NOT a medical/diagnostic tool.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.db.supabase_client import SupabaseConfigurationError, get_supabase_client
from app.security import require_user

router = APIRouter(tags=["checkins"])


class CheckinResponse(BaseModel):
    id: str
    inbox_item_id: str
    as_of: Optional[str] = None
    energy: Optional[int] = None
    mood: Optional[str] = None
    sleep_hours: Optional[float] = None
    stress: Optional[int] = None
    activity: Optional[str] = None
    notes: Optional[str] = None
    created_at: str


class CheckinsListResponse(BaseModel):
    items: list[CheckinResponse]
    total: int


@router.get("/checkins", dependencies=[Depends(require_user)])
def list_checkins() -> CheckinsListResponse:
    try:
        client = get_supabase_client()
    except SupabaseConfigurationError as exc:
        raise HTTPException(status_code=500, detail=f"Database configuration error: {exc}")

    try:
        result = (
            client.table("lifestyle_checkins")
            .select("*")
            .order("created_at", desc=True)
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database query failed") from exc

    items = [CheckinResponse(**row) for row in result.data]
    return CheckinsListResponse(items=items, total=len(items))
