from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.db.supabase_client import SupabaseConfigurationError, get_supabase_client
from app.security import require_dev_admin_token

router = APIRouter()


class CaptureContext(BaseModel):
    source: str
    raw_text: Optional[str] = None
    transcript: Optional[str] = None
    processing_status: str


class InboxItemResponse(BaseModel):
    id: str
    capture_event_id: Optional[str] = None
    item_type: str
    review_status: str
    title: Optional[str] = None
    body: Optional[str] = None
    structured_json: dict
    confidence: Optional[float] = None
    created_at: str
    updated_at: str
    reviewed_at: Optional[str] = None
    capture: Optional[CaptureContext] = None


class InboxResponse(BaseModel):
    items: list[InboxItemResponse]
    total: int


@router.get("/inbox", dependencies=[Depends(require_dev_admin_token)])
def get_inbox() -> InboxResponse:
    try:
        client = get_supabase_client()
    except SupabaseConfigurationError as exc:
        raise HTTPException(status_code=500, detail=f"Database configuration error: {exc}")

    try:
        result = (
            client.table("inbox_items")
            .select("*, capture_events(source, raw_text, transcript, processing_status)")
            .in_("review_status", ["pending", "needs_manual_classification"])
            .order("created_at", desc=True)
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database query failed") from exc

    items = []
    for row in result.data:
        capture_data = row.pop("capture_events", None)
        capture = CaptureContext(**capture_data) if capture_data else None
        items.append(InboxItemResponse(**row, capture=capture))

    return InboxResponse(items=items, total=len(items))
