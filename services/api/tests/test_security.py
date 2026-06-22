from datetime import timedelta

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
import app.security as security
from app.security import _jwks_url, require_user
from jwt.exceptions import PyJWKClientConnectionError, PyJWKClientError
from cryptography.hazmat.primitives.asymmetric import ec
from tests.conftest import (
    TEST_OWNER_USER_ID,
    mint_test_token,
)

client = TestClient(app)


def test_valid_owner_token_returns_subject():
    token = mint_test_token()
    assert require_user(f"Bearer {token}") == TEST_OWNER_USER_ID


def test_expired_token_returns_401():
    with pytest.raises(HTTPException) as exc:
        require_user(f"Bearer {mint_test_token(expires_delta=timedelta(seconds=-30))}")
    assert exc.value.status_code == 401
    assert exc.value.detail == "Token expired"


def test_bad_signature_returns_401():
    different_private_key = ec.generate_private_key(ec.SECP256R1())
    with pytest.raises(HTTPException) as exc:
        require_user(f"Bearer {mint_test_token(private_key=different_private_key)}")
    assert exc.value.status_code == 401
    assert exc.value.detail == "Invalid token"


def test_wrong_audience_returns_401():
    with pytest.raises(HTTPException) as exc:
        require_user(f"Bearer {mint_test_token(audience='wrong-audience')}")
    assert exc.value.status_code == 401


def test_non_owner_subject_returns_403():
    with pytest.raises(HTTPException) as exc:
        require_user(f"Bearer {mint_test_token(sub='different-user')}")
    assert exc.value.status_code == 403
    assert exc.value.detail == "Forbidden"


@pytest.mark.parametrize("authorization", [None, "", "Basic abc", "Bearer", "Bearer   "])
def test_missing_or_malformed_header_returns_401(authorization):
    with pytest.raises(HTTPException) as exc:
        require_user(authorization)
    assert exc.value.status_code == 401


@pytest.mark.parametrize("missing_var", ["SUPABASE_URL", "OWNER_USER_ID"])
def test_missing_auth_configuration_returns_500(monkeypatch, missing_var):
    monkeypatch.delenv(missing_var, raising=False)
    with pytest.raises(HTTPException) as exc:
        require_user(f"Bearer {mint_test_token()}")
    assert exc.value.status_code == 500
    assert exc.value.detail == "Server misconfiguration: auth is not configured"


def test_protected_route_rejects_missing_token():
    assert client.get("/inbox").status_code == 401


def test_public_health_does_not_require_auth_configuration(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("OWNER_USER_ID", raising=False)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_valid_owner_token_allows_protected_route():
    response = client.get(
        "/portfolio",
        headers={"Authorization": f"Bearer {mint_test_token()}"},
    )
    assert response.status_code == 200


def test_protected_route_rejects_non_owner_token():
    response = client.get(
        "/inbox",
        headers={"Authorization": f"Bearer {mint_test_token(sub='different-user')}"},
    )
    assert response.status_code == 403


def test_jwks_url_uses_supabase_project_url():
    assert _jwks_url("https://project.supabase.co/") == (
        "https://project.supabase.co/auth/v1/.well-known/jwks.json"
    )


def test_production_decode_is_restricted_to_es256(monkeypatch):
    captured = {}

    def capture_decode(token, key, **kwargs):
        captured.update(kwargs)
        return {"sub": TEST_OWNER_USER_ID, "aud": "authenticated", "exp": 4_102_444_800}

    monkeypatch.setattr(security.jwt, "decode", capture_decode)
    assert require_user(f"Bearer {mint_test_token()}") == TEST_OWNER_USER_ID
    assert captured["algorithms"] == ["ES256"]
    assert captured["audience"] == "authenticated"
    assert captured["options"] == {"require": ["exp", "sub", "aud"]}


def test_jwks_connection_failure_returns_503(monkeypatch):
    def fail_to_fetch(token, url):
        raise PyJWKClientConnectionError("network detail")

    monkeypatch.setattr("app.security._get_signing_key", fail_to_fetch)
    with pytest.raises(HTTPException) as exc:
        require_user(f"Bearer {mint_test_token()}")
    assert exc.value.status_code == 503
    assert exc.value.detail == "Authentication service unavailable"


def test_unknown_signing_key_returns_401(monkeypatch):
    def unknown_key(token, url):
        raise PyJWKClientError("unknown kid")

    monkeypatch.setattr("app.security._get_signing_key", unknown_key)
    with pytest.raises(HTTPException) as exc:
        require_user(f"Bearer {mint_test_token()}")
    assert exc.value.status_code == 401
    assert exc.value.detail == "Invalid token"
