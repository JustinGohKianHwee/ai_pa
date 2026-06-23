"""
Decision Journal domain module (Phase 21) — read + minimal status toggle.

Confirmed decisions are created by the atomic confirm_decision_item RPC (see review.py and
supabase/migrations/0016_decisions.sql). This router reads decisions and toggles their status
(active/reversed/archived) — the only field mutable after confirmation, mirroring goals.
Decision content is edited in the inbox before confirmation, not here. Status changes do not
write memory_events.
"""
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.db.supabase_client import SupabaseConfigurationError, get_supabase_client
from app.security import require_user

router = APIRouter(tags=["decisions"])

DecisionStatus = Literal["active", "reversed", "archived"]


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


class DecisionResponse(BaseModel):
    id: str
    inbox_item_id: str
    decision: str
    reason: Optional[str] = None
    options_considered: Optional[str] = None
    expected_outcome: Optional[str] = None
    confidence: Optional[float] = None
    category: Optional[str] = None
    decided_at: Optional[str] = None
    status: str
    notes: Optional[str] = None
    created_at: str
    updated_at: str


class DecisionsListResponse(BaseModel):
    items: list[DecisionResponse]
    total: int


class DecisionStatusUpdate(BaseModel):
    status: DecisionStatus


@router.get("/decisions", dependencies=[Depends(require_user)])
def list_decisions() -> DecisionsListResponse:
    try:
        client = get_supabase_client()
    except SupabaseConfigurationError as exc:
        raise HTTPException(status_code=500, detail=f"Database configuration error: {exc}")

    try:
        result = (
            client.table("decisions")
            .select("*")
            .order("created_at", desc=True)
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database query failed") from exc

    items = [DecisionResponse(**row) for row in result.data]
    return DecisionsListResponse(items=items, total=len(items))


@router.patch("/decisions/{decision_id}/status", dependencies=[Depends(require_user)])
def update_decision_status(decision_id: str, body: DecisionStatusUpdate) -> DecisionResponse:
    try:
        client = get_supabase_client()
    except SupabaseConfigurationError as exc:
        raise HTTPException(status_code=500, detail=f"Database configuration error: {exc}")

    try:
        result = client.table("decisions").select("*").eq("id", decision_id).execute()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database query failed") from exc

    if not result.data:
        raise HTTPException(status_code=404, detail="Decision not found")

    decision = result.data[0]

    # Idempotent: already in the requested status.
    if decision["status"] == body.status:
        return DecisionResponse(**decision)

    try:
        updated = (
            client.table("decisions")
            .update({"status": body.status, "updated_at": _now_utc()})
            .eq("id", decision_id)
            .eq("status", decision["status"])
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database update failed") from exc

    if not updated.data:
        # Concurrent status change — refetch to determine the outcome.
        try:
            refetch = client.table("decisions").select("*").eq("id", decision_id).execute()
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Database query failed") from exc

        if not refetch.data:
            raise HTTPException(status_code=404, detail="Decision not found")

        current = refetch.data[0]
        if current["status"] == body.status:
            return DecisionResponse(**current)
        raise HTTPException(
            status_code=409, detail="Decision was modified concurrently; status update failed"
        )

    return DecisionResponse(**updated.data[0])
