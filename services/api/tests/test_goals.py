"""
Tests for GET /goals and PATCH /goals/{id}/status (Phase 20).

Goals are created by confirm_goal_item. This router reads goals and toggles their status
(active/achieved/abandoned) — the only post-confirm mutation, mirroring tasks.complete.
"""
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.db.supabase_client import SupabaseConfigurationError
from app.main import app
from app.services.classifier import GoalStructuredJson

client = TestClient(app)

from tests.conftest import mint_test_token

VALID_TOKEN = mint_test_token()

GOAL_ROW = {
    "id": "goal-1",
    "inbox_item_id": "inbox-1",
    "owner_id": "owner-1",
    "title": "Reach 100k portfolio",
    "description": None,
    "target": "100000",
    "target_date": "end 2027",
    "status": "active",
    "created_at": "2026-06-24T01:00:00+00:00",
    "updated_at": "2026-06-24T01:00:00+00:00",
}


def _auth() -> dict:
    return {"Authorization": f"Bearer {VALID_TOKEN}"}


def _list_mock(data: list) -> MagicMock:
    q = MagicMock()
    for method in ("select", "eq", "order"):
        getattr(q, method).return_value = q
    q.execute.return_value = MagicMock(data=data)
    mock = MagicMock()
    mock.table.return_value = q
    return mock


def _patch_mock(execute_results: list) -> MagicMock:
    """Self-returning chain whose .execute yields each result in turn."""
    q = MagicMock()
    for method in ("select", "update", "eq"):
        getattr(q, method).return_value = q
    q.execute.side_effect = [MagicMock(data=d) for d in execute_results]
    mock = MagicMock()
    mock.table.return_value = q
    return mock


# --- GET /goals ---


def test_auth_missing_token_returns_401():
    assert client.get("/goals").status_code == 401


def test_auth_non_owner_returns_403():
    token = mint_test_token(sub="00000000-0000-0000-0000-0000000000ff")
    assert client.get("/goals", headers={"Authorization": f"Bearer {token}"}).status_code == 403


def test_empty_list():
    mock = _list_mock([])
    with patch("app.routes.goals.get_supabase_client", return_value=mock):
        res = client.get("/goals", headers=_auth())
    assert res.status_code == 200
    assert res.json() == {"items": [], "total": 0}


def test_shape_and_total():
    mock = _list_mock([GOAL_ROW])
    with patch("app.routes.goals.get_supabase_client", return_value=mock):
        res = client.get("/goals", headers=_auth())
    body = res.json()
    assert body["total"] == 1
    assert body["items"][0]["title"] == "Reach 100k portfolio"
    assert body["items"][0]["status"] == "active"


def test_query_failure_returns_503():
    mock = MagicMock()
    q = mock.table.return_value
    for method in ("select", "eq", "order"):
        getattr(q, method).return_value = q
    q.execute.side_effect = Exception("boom")
    with patch("app.routes.goals.get_supabase_client", return_value=mock):
        assert client.get("/goals", headers=_auth()).status_code == 503


# --- PATCH /goals/{id}/status ---


def test_status_update_succeeds():
    updated = {**GOAL_ROW, "status": "achieved"}
    mock = _patch_mock([[GOAL_ROW], [updated]])  # fetch, then update
    with patch("app.routes.goals.get_supabase_client", return_value=mock):
        res = client.patch(
            "/goals/goal-1/status", json={"status": "achieved"}, headers=_auth()
        )
    assert res.status_code == 200
    assert res.json()["status"] == "achieved"


def test_status_update_idempotent_when_already_in_status():
    mock = _patch_mock([[GOAL_ROW]])  # fetch only; status already 'active'
    with patch("app.routes.goals.get_supabase_client", return_value=mock):
        res = client.patch(
            "/goals/goal-1/status", json={"status": "active"}, headers=_auth()
        )
    assert res.status_code == 200
    assert res.json()["status"] == "active"


def test_status_update_invalid_value_returns_422():
    res = client.patch("/goals/goal-1/status", json={"status": "done"}, headers=_auth())
    assert res.status_code == 422


def test_status_update_not_found_returns_404():
    mock = _patch_mock([[]])  # fetch returns nothing
    with patch("app.routes.goals.get_supabase_client", return_value=mock):
        res = client.patch(
            "/goals/missing/status", json={"status": "achieved"}, headers=_auth()
        )
    assert res.status_code == 404


def test_status_update_concurrent_conflict_returns_409():
    # fetch(active) → update(no rows) → refetch shows a different status than requested
    mock = _patch_mock([[GOAL_ROW], [], [{**GOAL_ROW, "status": "abandoned"}]])
    with patch("app.routes.goals.get_supabase_client", return_value=mock):
        res = client.patch(
            "/goals/goal-1/status", json={"status": "achieved"}, headers=_auth()
        )
    assert res.status_code == 409


# --- classifier schema ---


def test_goal_schema_accepts_valid():
    m = GoalStructuredJson.model_validate(
        {"title": "Save 50k", "target": "50000", "target_date": "2027"}
    )
    assert m.title == "Save 50k"


def test_goal_schema_requires_title():
    with pytest.raises(Exception):
        GoalStructuredJson.model_validate({"target": "50000"})


def test_goal_schema_rejects_extra_field():
    with pytest.raises(Exception):
        GoalStructuredJson.model_validate({"title": "x", "progress": 10})
