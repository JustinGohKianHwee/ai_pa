"""
Tests for GET /decisions and PATCH /decisions/{id}/status (Phase 21).

Decisions are created by confirm_decision_item. This router reads decisions and toggles their
status (active/reversed/archived) — the only post-confirm mutation, mirroring goals.
"""
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.db.supabase_client import SupabaseConfigurationError
from app.main import app
from app.services.classifier import DecisionStructuredJson

client = TestClient(app)

from tests.conftest import mint_test_token

VALID_TOKEN = mint_test_token()

DECISION_ROW = {
    "id": "dec-1",
    "inbox_item_id": "inbox-1",
    "owner_id": "owner-1",
    "decision": "Term insurance over whole life",
    "reason": "Want pure protection",
    "options_considered": "term, whole life",
    "expected_outcome": None,
    "confidence": 0.8,
    "category": "insurance",
    "decided_at": "today",
    "status": "active",
    "notes": None,
    "created_at": "2026-06-24T01:00:00+00:00",
    "updated_at": "2026-06-24T01:00:00+00:00",
}


def _auth() -> dict:
    return {"Authorization": f"Bearer {VALID_TOKEN}"}


def _list_mock(data: list) -> MagicMock:
    mock = MagicMock()
    mock.table.return_value.select.return_value.order.return_value.execute.return_value = (
        MagicMock(data=data)
    )
    return mock


def _patch_mock(execute_results: list) -> MagicMock:
    q = MagicMock()
    for method in ("select", "update", "eq"):
        getattr(q, method).return_value = q
    q.execute.side_effect = [MagicMock(data=d) for d in execute_results]
    mock = MagicMock()
    mock.table.return_value = q
    return mock


# --- GET /decisions ---


def test_auth_missing_token_returns_401():
    assert client.get("/decisions").status_code == 401


def test_auth_non_owner_returns_403():
    token = mint_test_token(sub="00000000-0000-0000-0000-0000000000ff")
    assert client.get("/decisions", headers={"Authorization": f"Bearer {token}"}).status_code == 403


def test_empty_list():
    mock = _list_mock([])
    with patch("app.routes.decisions.get_supabase_client", return_value=mock):
        res = client.get("/decisions", headers=_auth())
    assert res.status_code == 200
    assert res.json() == {"items": [], "total": 0}


def test_shape_and_total():
    mock = _list_mock([DECISION_ROW])
    with patch("app.routes.decisions.get_supabase_client", return_value=mock):
        res = client.get("/decisions", headers=_auth())
    body = res.json()
    assert body["total"] == 1
    assert body["items"][0]["decision"] == "Term insurance over whole life"
    assert body["items"][0]["confidence"] == 0.8
    assert body["items"][0]["status"] == "active"


def test_orders_newest_first():
    mock = _list_mock([DECISION_ROW])
    with patch("app.routes.decisions.get_supabase_client", return_value=mock):
        client.get("/decisions", headers=_auth())
    mock.table.return_value.select.return_value.order.assert_called_once_with(
        "created_at", desc=True
    )


def test_query_failure_returns_503():
    mock = MagicMock()
    mock.table.return_value.select.return_value.order.return_value.execute.side_effect = (
        Exception("boom")
    )
    with patch("app.routes.decisions.get_supabase_client", return_value=mock):
        assert client.get("/decisions", headers=_auth()).status_code == 503


def test_db_config_error_returns_500():
    with patch(
        "app.routes.decisions.get_supabase_client",
        side_effect=SupabaseConfigurationError("missing key"),
    ):
        assert client.get("/decisions", headers=_auth()).status_code == 500


# --- PATCH /decisions/{id}/status ---


def test_status_update_succeeds():
    updated = {**DECISION_ROW, "status": "reversed"}
    mock = _patch_mock([[DECISION_ROW], [updated]])
    with patch("app.routes.decisions.get_supabase_client", return_value=mock):
        res = client.patch(
            "/decisions/dec-1/status", json={"status": "reversed"}, headers=_auth()
        )
    assert res.status_code == 200
    assert res.json()["status"] == "reversed"


def test_status_update_idempotent():
    mock = _patch_mock([[DECISION_ROW]])  # already 'active'
    with patch("app.routes.decisions.get_supabase_client", return_value=mock):
        res = client.patch(
            "/decisions/dec-1/status", json={"status": "active"}, headers=_auth()
        )
    assert res.status_code == 200
    assert res.json()["status"] == "active"


def test_status_update_invalid_value_returns_422():
    res = client.patch("/decisions/dec-1/status", json={"status": "resolved"}, headers=_auth())
    assert res.status_code == 422


def test_status_update_not_found_returns_404():
    mock = _patch_mock([[]])
    with patch("app.routes.decisions.get_supabase_client", return_value=mock):
        res = client.patch(
            "/decisions/missing/status", json={"status": "archived"}, headers=_auth()
        )
    assert res.status_code == 404


def test_status_update_concurrent_conflict_returns_409():
    mock = _patch_mock([[DECISION_ROW], [], [{**DECISION_ROW, "status": "archived"}]])
    with patch("app.routes.decisions.get_supabase_client", return_value=mock):
        res = client.patch(
            "/decisions/dec-1/status", json={"status": "reversed"}, headers=_auth()
        )
    assert res.status_code == 409


# --- classifier schema ---


def test_decision_schema_accepts_valid():
    m = DecisionStructuredJson.model_validate(
        {"decision": "Use Render", "reason": "free tier", "confidence": 0.7}
    )
    assert m.decision == "Use Render"


def test_decision_schema_requires_decision():
    with pytest.raises(Exception):
        DecisionStructuredJson.model_validate({"reason": "x"})


def test_decision_schema_rejects_extra_field():
    with pytest.raises(Exception):
        DecisionStructuredJson.model_validate({"decision": "x", "outcome_score": 5})


def test_decision_schema_rejects_confidence_out_of_range():
    with pytest.raises(Exception):
        DecisionStructuredJson.model_validate({"decision": "x", "confidence": 1.5})
