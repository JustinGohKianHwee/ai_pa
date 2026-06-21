"""
Tests for GET /tasks and PATCH /tasks/{id}/complete (Phase 8 tasks module).

All Supabase access is mocked. Task creation is covered in test_review.py (the
atomic confirm RPC); this file covers reading and completing tasks.
"""
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.db.supabase_client import SupabaseConfigurationError
from app.main import app

client = TestClient(app)

VALID_TOKEN = "test-dev-admin-token-xyz"
TASK_ID = "task-uuid-1"

OPEN_TASK = {
    "id": TASK_ID,
    "inbox_item_id": "inbox-1",
    "title": "Pay credit card bill",
    "urgency": "this_week",
    "due_date": "next Friday",
    "notes": None,
    "status": "open",
    "completed_at": None,
    "created_at": "2024-01-02T12:00:00+00:00",
    "updated_at": "2024-01-02T12:00:00+00:00",
}

OLDER_OPEN_TASK = {
    **OPEN_TASK,
    "id": "task-uuid-2",
    "inbox_item_id": "inbox-2",
    "title": "Call mum",
    "urgency": "today",
    "created_at": "2024-01-01T09:00:00+00:00",
}

COMPLETED_TASK = {
    **OPEN_TASK,
    "status": "completed",
    "completed_at": "2024-01-03T09:00:00+00:00",
}


def _auth_header(token: str = VALID_TOKEN) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _make_list_mock(data: list) -> MagicMock:
    mock = MagicMock()
    (
        mock.table.return_value
        .select.return_value
        .order.return_value
        .execute.return_value
    ) = MagicMock(data=data)
    return mock


def _make_complete_mock(select_data: list, update_data: list | None = None) -> MagicMock:
    mock = MagicMock()
    mock.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
        data=select_data
    )
    (
        mock.table.return_value
        .update.return_value
        .eq.return_value
        .eq.return_value
        .execute.return_value
    ) = MagicMock(data=update_data or [])
    return mock


# ---------------------------------------------------------------------------
# GET /tasks — auth
# ---------------------------------------------------------------------------


def test_list_tasks_missing_token_returns_403(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    response = client.get("/tasks")
    assert response.status_code == 403


def test_list_tasks_wrong_token_returns_403(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    response = client.get("/tasks", headers={"Authorization": "Bearer wrong"})
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# GET /tasks — read
# ---------------------------------------------------------------------------


def test_list_tasks_empty_returns_empty_list(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    mock = _make_list_mock([])
    with patch("app.routes.tasks.get_supabase_client", return_value=mock):
        response = client.get("/tasks", headers=_auth_header())
    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["total"] == 0


def test_list_tasks_returns_shape_and_total(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    mock = _make_list_mock([OPEN_TASK, OLDER_OPEN_TASK])
    with patch("app.routes.tasks.get_supabase_client", return_value=mock):
        response = client.get("/tasks", headers=_auth_header())
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert body["items"][0]["id"] == TASK_ID
    assert body["items"][0]["title"] == "Pay credit card bill"
    assert body["items"][0]["status"] == "open"


def test_list_tasks_orders_newest_first(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    mock = _make_list_mock([OPEN_TASK, OLDER_OPEN_TASK])
    with patch("app.routes.tasks.get_supabase_client", return_value=mock):
        client.get("/tasks", headers=_auth_header())
    mock.table.return_value.select.return_value.order.assert_called_once_with(
        "created_at", desc=True
    )


def test_list_tasks_db_config_error_returns_500(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    with patch(
        "app.routes.tasks.get_supabase_client",
        side_effect=SupabaseConfigurationError("missing"),
    ):
        response = client.get("/tasks", headers=_auth_header())
    assert response.status_code == 500


def test_list_tasks_query_failure_returns_503(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    mock = MagicMock()
    mock.table.return_value.select.return_value.order.return_value.execute.side_effect = Exception(
        "boom"
    )
    with patch("app.routes.tasks.get_supabase_client", return_value=mock):
        response = client.get("/tasks", headers=_auth_header())
    assert response.status_code == 503


# ---------------------------------------------------------------------------
# PATCH /tasks/{id}/complete
# ---------------------------------------------------------------------------


def test_complete_missing_token_returns_403(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    response = client.patch(f"/tasks/{TASK_ID}/complete")
    assert response.status_code == 403


def test_complete_open_task_returns_200_completed(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    mock = _make_complete_mock(select_data=[OPEN_TASK], update_data=[COMPLETED_TASK])
    with patch("app.routes.tasks.get_supabase_client", return_value=mock):
        response = client.patch(f"/tasks/{TASK_ID}/complete", headers=_auth_header())
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["completed_at"] is not None


def test_complete_already_completed_is_idempotent_200(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    mock = _make_complete_mock(select_data=[COMPLETED_TASK])
    with patch("app.routes.tasks.get_supabase_client", return_value=mock):
        response = client.patch(f"/tasks/{TASK_ID}/complete", headers=_auth_header())
    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    mock.table.return_value.update.assert_not_called()


def test_complete_missing_task_returns_404(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    mock = _make_complete_mock(select_data=[])
    with patch("app.routes.tasks.get_supabase_client", return_value=mock):
        response = client.patch(f"/tasks/{TASK_ID}/complete", headers=_auth_header())
    assert response.status_code == 404


def test_complete_db_config_error_returns_500(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    with patch(
        "app.routes.tasks.get_supabase_client",
        side_effect=SupabaseConfigurationError("missing"),
    ):
        response = client.patch(f"/tasks/{TASK_ID}/complete", headers=_auth_header())
    assert response.status_code == 500


def test_complete_query_failure_returns_503(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    mock = MagicMock()
    mock.table.return_value.select.return_value.eq.return_value.execute.side_effect = Exception(
        "boom"
    )
    with patch("app.routes.tasks.get_supabase_client", return_value=mock):
        response = client.patch(f"/tasks/{TASK_ID}/complete", headers=_auth_header())
    assert response.status_code == 503
