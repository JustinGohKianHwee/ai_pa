from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.main import app
from app.db.supabase_client import SupabaseConfigurationError

client = TestClient(app)

from tests.conftest import mint_test_token

VALID_TOKEN = mint_test_token()


def test_health_db_rejects_missing_auth_header(monkeypatch):
    response = client.get("/health/db")
    assert response.status_code == 401


def test_health_db_rejects_wrong_token(monkeypatch):
    response = client.get("/health/db", headers={"Authorization": "Bearer wrong-token"})
    assert response.status_code == 401


def test_health_db_returns_500_when_token_not_configured(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    response = client.get("/health/db", headers={"Authorization": "Bearer anything"})
    assert response.status_code == 500


def test_health_db_returns_200_with_mocked_supabase(monkeypatch):

    mock_supabase = MagicMock()
    mock_supabase.table.return_value.select.return_value.limit.return_value.execute.return_value.data = []

    with patch("app.routes.health_db.get_supabase_client", return_value=mock_supabase):
        response = client.get("/health/db", headers={"Authorization": f"Bearer {VALID_TOKEN}"})

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "connected"}
    mock_supabase.table.assert_called_once_with("capture_events")
    mock_supabase.table.return_value.select.assert_called_once_with("id")
    mock_supabase.table.return_value.select.return_value.limit.assert_called_once_with(1)
    mock_supabase.table.return_value.select.return_value.limit.return_value.execute.assert_called_once_with()


def test_health_db_returns_500_when_supabase_client_raises(monkeypatch):

    with patch(
        "app.routes.health_db.get_supabase_client",
        side_effect=SupabaseConfigurationError("SUPABASE_URL"),
    ):
        response = client.get("/health/db", headers={"Authorization": f"Bearer {VALID_TOKEN}"})

    assert response.status_code == 500


def test_health_db_returns_safe_503_when_query_fails(monkeypatch):
    mock_supabase = MagicMock()
    mock_supabase.table.return_value.select.return_value.limit.return_value.execute.side_effect = (
        RuntimeError("sensitive upstream detail")
    )

    with patch("app.routes.health_db.get_supabase_client", return_value=mock_supabase):
        response = client.get(
            "/health/db", headers={"Authorization": f"Bearer {VALID_TOKEN}"}
        )

    assert response.status_code == 503
    assert response.json() == {"detail": "Database connectivity check failed"}
