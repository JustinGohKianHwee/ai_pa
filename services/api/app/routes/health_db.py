from fastapi import APIRouter, Depends, HTTPException

from app.db.supabase_client import SupabaseConfigurationError, get_supabase_client
from app.security import require_user

router = APIRouter()


@router.get("/health/db", dependencies=[Depends(require_user)])
def health_db() -> dict:
    try:
        client = get_supabase_client()
    except SupabaseConfigurationError as exc:
        raise HTTPException(status_code=500, detail=f"Database configuration error: {exc}")
    try:
        client.table("capture_events").select("id").limit(1).execute()
    except Exception as exc:
        raise HTTPException(
            status_code=503, detail="Database connectivity check failed"
        ) from exc
    return {"status": "ok", "database": "connected"}
