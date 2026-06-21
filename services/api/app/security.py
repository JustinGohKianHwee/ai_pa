import os

from fastapi import Header, HTTPException


def require_dev_admin_token(authorization: str | None = Header(default=None)) -> None:
    token = os.getenv("DEV_ADMIN_TOKEN")
    if not token:
        raise HTTPException(status_code=500, detail="Server misconfiguration: DEV_ADMIN_TOKEN is not set")
    if authorization != f"Bearer {token}":
        raise HTTPException(status_code=403, detail="Forbidden")
