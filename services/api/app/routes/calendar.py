from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.db.supabase_client import SupabaseConfigurationError, get_supabase_client
from app.security import require_user

router = APIRouter(tags=["calendar"])


class CalendarIntentResponse(BaseModel):
    id: str
    inbox_item_id: str
    title: str
    proposed_datetime: Optional[str] = None
    location: Optional[str] = None
    notes: Optional[str] = None
    created_at: str


class CalendarIntentsListResponse(BaseModel):
    items: list[CalendarIntentResponse]
    total: int


@router.get("/calendar_intents", dependencies=[Depends(require_user)])
def get_calendar_intents() -> CalendarIntentsListResponse:
    try:
        client = get_supabase_client()
    except SupabaseConfigurationError as exc:
        raise HTTPException(status_code=500, detail=f"Database configuration error: {exc}")

    try:
        result = (
            client.table("calendar_intents")
            .select("*")
            .order("created_at", desc=True)
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database query failed") from exc

    items = [CalendarIntentResponse(**row) for row in result.data]
    return CalendarIntentsListResponse(items=items, total=len(items))
