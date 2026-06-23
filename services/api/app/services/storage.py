"""
Supabase Storage helpers for food photos (Phase 17).

Photos live in a PRIVATE bucket (`food-photos`). The backend (service-role client) is the
only reader/writer; the frontend never gets a public URL — only short-lived signed URLs
minted here. Never log signed URLs or raw image bytes.
"""
import logging
from typing import Any, Optional

from app.db.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)

FOOD_PHOTOS_BUCKET = "food-photos"


def upload_food_photo(
    image_bytes: bytes, object_path: str, content_type: str = "image/jpeg"
) -> str:
    """Upload photo bytes to the private bucket; return the stored object path."""
    client = get_supabase_client()
    client.storage.from_(FOOD_PHOTOS_BUCKET).upload(
        object_path,
        image_bytes,
        {"content-type": content_type, "upsert": "true"},
    )
    return object_path


def signed_food_photo_url(object_path: Optional[str], expires_in: int = 600) -> Optional[str]:
    """Create a short-lived signed URL for a stored photo. Returns None on any failure."""
    if not object_path:
        return None
    try:
        client = get_supabase_client()
        res: Any = client.storage.from_(FOOD_PHOTOS_BUCKET).create_signed_url(
            object_path, expires_in
        )
    except Exception:
        logger.warning("Failed to create signed URL for a food photo")
        return None

    if isinstance(res, dict):
        return res.get("signedURL") or res.get("signedUrl") or res.get("signed_url")
    return getattr(res, "signed_url", None) or getattr(res, "signedURL", None)
