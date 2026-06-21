"""
Tasks domain module (Phase 8) — read + complete.

Confirmed tasks are created by the atomic confirm_task_item RPC (see review.py and
supabase/migrations/0002_tasks.sql). This router only reads tasks and marks them complete.
Task editing happens in the inbox before confirmation, not here.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.db.supabase_client import SupabaseConfigurationError, get_supabase_client
from app.security import require_dev_admin_token

router = APIRouter(tags=["tasks"])


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskResponse(BaseModel):
    id: str
    inbox_item_id: str
    title: str
    urgency: Optional[str] = None
    due_date: Optional[str] = None
    notes: Optional[str] = None
    status: str
    completed_at: Optional[str] = None
    created_at: str
    updated_at: str


class TasksListResponse(BaseModel):
    items: list[TaskResponse]
    total: int


@router.get("/tasks", dependencies=[Depends(require_dev_admin_token)])
def list_tasks() -> TasksListResponse:
    try:
        client = get_supabase_client()
    except SupabaseConfigurationError as exc:
        raise HTTPException(status_code=500, detail=f"Database configuration error: {exc}")

    try:
        result = (
            client.table("tasks")
            .select("*")
            .order("created_at", desc=True)
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database query failed") from exc

    items = [TaskResponse(**row) for row in result.data]
    return TasksListResponse(items=items, total=len(items))


@router.patch("/tasks/{task_id}/complete", dependencies=[Depends(require_dev_admin_token)])
def complete_task(task_id: str) -> TaskResponse:
    try:
        client = get_supabase_client()
    except SupabaseConfigurationError as exc:
        raise HTTPException(status_code=500, detail=f"Database configuration error: {exc}")

    try:
        result = client.table("tasks").select("*").eq("id", task_id).execute()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database query failed") from exc

    if not result.data:
        raise HTTPException(status_code=404, detail="Task not found")

    task = result.data[0]

    if task["status"] == "completed":
        return TaskResponse(**task)

    try:
        updated = (
            client.table("tasks")
            .update({"status": "completed", "completed_at": _now_utc()})
            .eq("id", task_id)
            .eq("status", "open")
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database update failed") from exc

    if not updated.data:
        # Concurrent completion — refetch to determine the outcome.
        try:
            refetch = client.table("tasks").select("*").eq("id", task_id).execute()
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Database query failed") from exc

        if not refetch.data:
            raise HTTPException(status_code=404, detail="Task not found")

        current = refetch.data[0]
        if current["status"] == "completed":
            return TaskResponse(**current)
        raise HTTPException(status_code=503, detail="Complete failed unexpectedly")

    return TaskResponse(**updated.data[0])
