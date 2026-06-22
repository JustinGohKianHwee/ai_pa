import os
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.db.supabase_client import SupabaseConfigurationError, get_supabase_client
from app.routes.telegram import _classify_and_update
from app.security import require_user

router = APIRouter(prefix="/inbox", tags=["inbox"])

FINAL_STATUSES = {"confirmed", "rejected"}
STUB_TYPE = "unknown"


class ClassifyResponse(BaseModel):
    id: str
    item_type: str
    review_status: str
    title: Optional[str] = None
    body: Optional[str] = None
    structured_json: dict[str, Any]
    confidence: Optional[float] = None


@router.post("/{inbox_id}/classify", dependencies=[Depends(require_user)])
async def reclassify_inbox_item(inbox_id: str) -> ClassifyResponse:
    """
    Admin/recovery endpoint — NOT part of the normal capture pipeline.

    Normal flow: Telegram → /telegram/webhook → classify_text() → inbox.
    This endpoint only processes stubs with item_type='unknown'. Items that have been
    successfully classified must be reviewed or rejected via the dashboard; they cannot
    be reclassified here. Returns 400 for confirmed, rejected, or already-classified items.

    Requires OPENAI_API_KEY; returns 503 if absent.
    """
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(
            status_code=503,
            detail="OPENAI_API_KEY is not configured; classification unavailable",
        )

    try:
        client = get_supabase_client()
    except SupabaseConfigurationError as exc:
        raise HTTPException(status_code=500, detail=f"Database configuration error: {exc}")

    try:
        row = (
            client.table("inbox_items")
            .select("*, capture_events(id, raw_text, transcript)")
            .eq("id", inbox_id)
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database query failed") from exc

    if not row.data:
        raise HTTPException(status_code=404, detail="Inbox item not found")

    item = row.data[0]

    if item.get("review_status") in FINAL_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot reclassify an item with review_status='{item['review_status']}'",
        )

    # Recovery only: reject items that have already been successfully classified.
    # Use the dashboard to review or reject them instead.
    if item.get("item_type") != STUB_TYPE:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Item already classified as '{item['item_type']}'. "
                "Review or reject it in the inbox instead."
            ),
        )

    # Resolve the text to classify: body → transcript → raw_text
    capture = item.get("capture_events") or {}
    text = item.get("body") or capture.get("transcript") or capture.get("raw_text") or ""
    if not text:
        raise HTTPException(status_code=400, detail="No text available to classify")

    capture_id = item.get("capture_event_id") or capture.get("id")

    await _classify_and_update(
        client=client,
        text=text,
        capture_id=capture_id,
        inbox_id=inbox_id,
    )

    # Fetch the updated row to return
    try:
        updated = (
            client.table("inbox_items")
            .select("id, item_type, review_status, title, body, structured_json, confidence")
            .eq("id", inbox_id)
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Failed to fetch updated item") from exc

    if not updated.data:
        raise HTTPException(status_code=503, detail="Failed to fetch updated item")

    return ClassifyResponse(**updated.data[0])
