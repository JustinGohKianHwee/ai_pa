"""
Exercise logs domain module (Phase 18) — read only.

Confirmed exercise logs are created by the atomic confirm_exercise_item RPC (see review.py
and supabase/migrations/0013_exercise_logs.sql). This router only reads exercise_logs. There
is no editing, completion, or deletion in Phase 18.

"Today" filtering contract (identical to /food_logs):
  ?date=today returns exercise logs whose created_at (UTC timestamptz) falls within the user's
  local calendar day, as defined by USER_TIMEZONE (IANA string, e.g. "Asia/Singapore"). Local
  midnight boundaries are computed at request time, then converted to UTC for the created_at
  query. "Today" means the day the workout was confirmed, not when it was performed. logged_at
  (the AI's free-text date string) is NOT used for filtering — display only.
  "today" is the ONLY accepted value for the date parameter; any other value returns 422.
"""
import os
from datetime import datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.db.supabase_client import SupabaseConfigurationError, get_supabase_client
from app.security import require_user

router = APIRouter(tags=["exercise"])


class ExerciseLogResponse(BaseModel):
    id: str
    inbox_item_id: str
    activity: str
    duration_min: Optional[float] = None
    distance_km: Optional[float] = None
    sets: Optional[int] = None
    reps: Optional[int] = None
    intensity: Optional[str] = None
    calories: Optional[float] = None
    logged_at: Optional[str] = None
    notes: Optional[str] = None
    created_at: str


class ExerciseTotals(BaseModel):
    duration_min: float = 0.0
    distance_km: float = 0.0
    calories: float = 0.0


class ExerciseLogsListResponse(BaseModel):
    items: list[ExerciseLogResponse]
    total: int
    totals: ExerciseTotals


@router.get("/exercise_logs", dependencies=[Depends(require_user)])
def list_exercise_logs(date: Optional[str] = None) -> ExerciseLogsListResponse:
    if date is not None and date != "today":
        raise HTTPException(
            status_code=422,
            detail="date parameter must be 'today' or omitted",
        )

    try:
        client = get_supabase_client()
    except SupabaseConfigurationError as exc:
        raise HTTPException(status_code=500, detail=f"Database configuration error: {exc}")

    try:
        if date == "today":
            user_tz = ZoneInfo(os.getenv("USER_TIMEZONE", "UTC"))
            today_local = datetime.now(user_tz).date()
            start_local = datetime.combine(today_local, time.min, tzinfo=user_tz)
            end_local = start_local + timedelta(days=1)
            start_utc = start_local.astimezone(timezone.utc)
            end_utc = end_local.astimezone(timezone.utc)
            result = (
                client.table("exercise_logs")
                .select("*")
                .gte("created_at", start_utc.isoformat())
                .lt("created_at", end_utc.isoformat())
                .order("created_at", desc=True)
                .execute()
            )
        else:
            result = (
                client.table("exercise_logs")
                .select("*")
                .order("created_at", desc=True)
                .execute()
            )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database query failed") from exc

    items: list[ExerciseLogResponse] = []
    totals = {"duration_min": 0.0, "distance_km": 0.0, "calories": 0.0}
    for row in result.data:
        items.append(
            ExerciseLogResponse(
                id=row["id"],
                inbox_item_id=row["inbox_item_id"],
                activity=row["activity"],
                duration_min=row.get("duration_min"),
                distance_km=row.get("distance_km"),
                sets=row.get("sets"),
                reps=row.get("reps"),
                intensity=row.get("intensity"),
                calories=row.get("calories"),
                logged_at=row.get("logged_at"),
                notes=row.get("notes"),
                created_at=row["created_at"],
            )
        )
        for key in totals:
            value = row.get(key)
            if value is not None:
                totals[key] += float(value)

    return ExerciseLogsListResponse(
        items=items, total=len(items), totals=ExerciseTotals(**totals)
    )
