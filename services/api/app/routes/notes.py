"""
Notes domain module (Phase 23a) — read-only list with optional text search.

Confirmed notes are created by the atomic confirm_note_item RPC (see review.py and
supabase/migrations/0020_notes_journal.sql). This router lists notes and supports a simple
deterministic content search (?q=, ILIKE) — no vectors (that's a later phase). Note content is
edited in the inbox before confirmation, not here; notes are immutable after confirmation.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.db.supabase_client import SupabaseConfigurationError, get_supabase_client
from app.security import require_user

router = APIRouter(tags=["notes"])


class NoteResponse(BaseModel):
    id: str
    inbox_item_id: str
    content: str
    tags: list[str] = []
    created_at: str


class NotesListResponse(BaseModel):
    items: list[NoteResponse]
    total: int


@router.get("/notes", dependencies=[Depends(require_user)])
def list_notes(q: Optional[str] = Query(default=None)) -> NotesListResponse:
    try:
        client = get_supabase_client()
    except SupabaseConfigurationError as exc:
        raise HTTPException(status_code=500, detail=f"Database configuration error: {exc}")

    try:
        query = client.table("notes").select("*")
        term = (q or "").strip()
        if term:
            # Deterministic substring search on content (single-user scale; no index needed).
            query = query.ilike("content", f"%{term}%")
        result = query.order("created_at", desc=True).execute()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database query failed") from exc

    items = [NoteResponse(**row) for row in result.data]
    return NotesListResponse(items=items, total=len(items))
