import pytest
from unittest.mock import patch

from app.db.supabase_client import get_supabase_client


def test_raises_when_supabase_url_missing(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "fake-service-key")
    with pytest.raises(ValueError, match="SUPABASE_URL"):
        get_supabase_client()


def test_raises_when_service_role_key_missing(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    with pytest.raises(ValueError, match="SUPABASE_SERVICE_ROLE_KEY"):
        get_supabase_client()


def test_raises_when_both_missing(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    with pytest.raises(ValueError, match="SUPABASE_URL"):
        get_supabase_client()


def test_creates_client_with_backend_service_role_credentials(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "fake-service-role-key")

    with patch("app.db.supabase_client.create_client") as mock_create_client:
        result = get_supabase_client()

    mock_create_client.assert_called_once_with(
        "https://example.supabase.co", "fake-service-role-key"
    )
    assert result is mock_create_client.return_value


def test_rejects_supabase_url_with_rest_path(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co/rest/v1/")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "fake-service-role-key")

    with pytest.raises(ValueError, match="project base URL"):
        get_supabase_client()
