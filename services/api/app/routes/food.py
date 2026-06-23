"""
Food logs domain module (Phase 11) — read only.

Confirmed food logs are created by the atomic confirm_food_item RPC (see review.py and
supabase/migrations/0006_food_logs.sql). This router only reads food_logs. There is no
food log editing, completion, or deletion in Phase 11.

"Today" filtering contract:
  ?date=today returns food logs whose created_at (UTC timestamptz) falls within the user's
  local calendar day, as defined by the USER_TIMEZONE environment variable (IANA timezone
  string, e.g. "Asia/Singapore"). Local midnight boundaries are computed at request time,
  then converted to UTC for the created_at query:

      created_at >= local_midnight_utc  AND  created_at < next_local_midnight_utc

  "Today" means the calendar day during which the user confirmed the food item, not when
  the meal was actually eaten. A meal confirmed at 11:59 PM SGT will appear in today's
  view; the same meal confirmed at 12:01 AM the next SGT day will not.

  logged_at (the AI's free-text date string, e.g. "lunchtime") is NOT used for filtering —
  it is a display field only.

  "today" is the ONLY accepted value for the date parameter. Any other value returns 422.
"""
import os
from datetime import datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.db.supabase_client import SupabaseConfigurationError, get_supabase_client
from app.security import require_user
from app.services.storage import signed_food_photo_url

router = APIRouter(tags=["food"])


class FoodLogResponse(BaseModel):
    id: str
    inbox_item_id: str
    description: str
    meal_type: Optional[str] = None
    logged_at: Optional[str] = None
    calories: Optional[float] = None
    protein_g: Optional[float] = None
    carbs_g: Optional[float] = None
    fat_g: Optional[float] = None
    image_url: Optional[str] = None
    created_at: str


class FoodTotals(BaseModel):
    calories: float = 0.0
    protein_g: float = 0.0
    carbs_g: float = 0.0
    fat_g: float = 0.0


class FoodLogsListResponse(BaseModel):
    items: list[FoodLogResponse]
    total: int
    totals: FoodTotals


@router.get("/food_logs", dependencies=[Depends(require_user)])
def list_food_logs(date: Optional[str] = None) -> FoodLogsListResponse:
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
            # Compute local midnight boundaries in the user's timezone and convert to UTC.
            # USER_TIMEZONE must be a valid IANA timezone string (e.g. "Asia/Singapore").
            # Defaults to "UTC" so the endpoint works even if the variable is not set.
            user_tz = ZoneInfo(os.getenv("USER_TIMEZONE", "UTC"))
            today_local = datetime.now(user_tz).date()
            start_local = datetime.combine(today_local, time.min, tzinfo=user_tz)
            end_local = start_local + timedelta(days=1)
            start_utc = start_local.astimezone(timezone.utc)
            end_utc = end_local.astimezone(timezone.utc)
            result = (
                client.table("food_logs")
                .select("*")
                .gte("created_at", start_utc.isoformat())
                .lt("created_at", end_utc.isoformat())
                .order("created_at", desc=True)
                .execute()
            )
        else:
            result = (
                client.table("food_logs")
                .select("*")
                .order("created_at", desc=True)
                .execute()
            )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database query failed") from exc

    items: list[FoodLogResponse] = []
    totals = {"calories": 0.0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0}
    for row in result.data:
        items.append(
            FoodLogResponse(
                id=row["id"],
                inbox_item_id=row["inbox_item_id"],
                description=row["description"],
                meal_type=row.get("meal_type"),
                logged_at=row.get("logged_at"),
                calories=row.get("calories"),
                protein_g=row.get("protein_g"),
                carbs_g=row.get("carbs_g"),
                fat_g=row.get("fat_g"),
                image_url=signed_food_photo_url(row.get("image_path")),
                created_at=row["created_at"],
            )
        )
        for key in totals:
            value = row.get(key)
            if value is not None:
                totals[key] += float(value)

    return FoodLogsListResponse(
        items=items, total=len(items), totals=FoodTotals(**totals)
    )
