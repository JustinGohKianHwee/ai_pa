"""
Journal domain module (Phase 23a) — read-only list.

Confirmed journal entries are created by the atomic confirm_journal_item RPC (see review.py and
supabase/migrations/0020_notes_journal.sql). This router lists entries newest-first. Content is
edited in the inbox before confirmation, not here; entries are immutable after confirmation.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.db.supabase_client import SupabaseConfigurationError, get_supabase_client
from app.security import require_user

router = APIRouter(tags=["journal"])


class JournalResponse(BaseModel):
    id: str
    inbox_item_id: str
    content: str
    mood: Optional[str] = None
    created_at: str


class JournalListResponse(BaseModel):
    items: list[JournalResponse]
    total: int


@router.get("/journal", dependencies=[Depends(require_user)])
def list_journal() -> JournalListResponse:
    try:
        client = get_supabase_client()
    except SupabaseConfigurationError as exc:
        raise HTTPException(status_code=500, detail=f"Database configuration error: {exc}")

    try:
        result = (
            client.table("journal_entries")
            .select("*")
            .order("created_at", desc=True)
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database query failed") from exc

    items = [JournalResponse(**row) for row in result.data]
    return JournalListResponse(items=items, total=len(items))
