import os
from functools import lru_cache

import jwt
from fastapi import Header, HTTPException
from jwt import ExpiredSignatureError, InvalidTokenError, PyJWKClient
from jwt.exceptions import PyJWKClientConnectionError, PyJWKClientError


def _jwks_url(supabase_url: str) -> str:
    return f"{supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"


@lru_cache(maxsize=4)
def _jwks_client(supabase_url: str) -> PyJWKClient:
    """Cache Supabase's JWKS for five minutes; refresh automatically on an unknown kid."""
    return PyJWKClient(
        _jwks_url(supabase_url),
        cache_jwk_set=True,
        lifespan=300,
        timeout=5,
    )


def _get_signing_key(token: str, supabase_url: str):
    return _jwks_client(supabase_url).get_signing_key_from_jwt(token).key


def require_user(authorization: str | None = Header(default=None)) -> str:
    """Verify a Supabase ES256 access token via JWKS and enforce the owner gate."""
    supabase_url = os.getenv("SUPABASE_URL")
    owner_user_id = os.getenv("OWNER_USER_ID")
    if not supabase_url or not owner_user_id:
        raise HTTPException(
            status_code=500,
            detail="Server misconfiguration: auth is not configured",
        )

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid token")

    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="Invalid token")

    try:
        signing_key = _get_signing_key(token, supabase_url)
        payload = jwt.decode(
            token,
            signing_key,
            algorithms=["ES256"],
            audience="authenticated",
            leeway=10,
            options={"require": ["exp", "sub", "aud"]},
        )
    except PyJWKClientConnectionError as exc:
        raise HTTPException(
            status_code=503,
            detail="Authentication service unavailable",
        ) from exc
    except PyJWKClientError as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc
    except ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="Token expired") from exc
    except InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc

    subject = payload.get("sub")
    if subject != owner_user_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    return subject
