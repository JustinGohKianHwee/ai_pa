"""
Tests for GET /timeline (Phase 19) — read-only feed over memory_events.

The Supabase client is mocked with a self-returning query chain so we can assert which
filters/order/limit were applied without a database. The route must never write.
"""
import base64
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.db.supabase_client import SupabaseConfigurationError
from app.main import app

client = TestClient(app)

from tests.conftest import mint_test_token

VALID_TOKEN = mint_test_token()


def _auth() -> dict:
    return {"Authorization": f"Bearer {VALID_TOKEN}"}


def _row(i: int, domain: str = "task", event_type: str = "confirmed", **payload) -> dict:
    return {
        "id": f"evt-{i}",
        "occurred_at": f"2026-06-2{i}T10:00:00+00:00",
        "domain": domain,
        "event_type": event_type,
        "source_table": "tasks",
        "source_id": f"src-{i}",
        "payload_json": payload or {"title": f"item {i}"},
    }


def _chain_mock(data: list):
    """Return (client_mock, query_mock) where every chain method returns the query mock."""
    q = MagicMock()
    for method in ("select", "order", "in_", "gte", "lt", "or_", "limit"):
        getattr(q, method).return_value = q
    q.execute.return_value = MagicMock(data=data)
    client_mock = MagicMock()
    client_mock.table.return_value = q
    return client_mock, q


# --- auth ---


def test_auth_missing_token_returns_401():
    assert client.get("/timeline").status_code == 401


def test_auth_wrong_token_returns_401():
    assert client.get("/timeline", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_auth_non_owner_returns_403():
    token = mint_test_token(sub="00000000-0000-0000-0000-0000000000ff")
    res = client.get("/timeline", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 403


# --- happy path / shape ---


def test_empty_returns_empty():
    cm, _ = _chain_mock([])
    with patch("app.routes.timeline.get_supabase_client", return_value=cm):
        res = client.get("/timeline", headers=_auth())
    assert res.status_code == 200
    assert res.json() == {"items": [], "next_cursor": None}


def test_entry_shape_and_payload_passthrough():
    rows = [_row(1, domain="food", event_type="confirmed", description="laksa", calories=550)]
    cm, _ = _chain_mock(rows)
    with patch("app.routes.timeline.get_supabase_client", return_value=cm):
        res = client.get("/timeline", headers=_auth())
    body = res.json()
    item = body["items"][0]
    assert item["domain"] == "food"
    assert item["event_type"] == "confirmed"
    assert item["source_id"] == "src-1"
    assert item["payload"] == {"description": "laksa", "calories": 550}
    assert body["next_cursor"] is None


def test_orders_by_occurred_at_then_id_desc():
    cm, q = _chain_mock([_row(1)])
    with patch("app.routes.timeline.get_supabase_client", return_value=cm):
        client.get("/timeline", headers=_auth())
    order_calls = [c.args for c in q.order.call_args_list]
    assert ("occurred_at",) == order_calls[0] or order_calls[0][0] == "occurred_at"
    assert any(c.args[0] == "id" for c in q.order.call_args_list)


# --- filters ---


def test_domain_filter_applied():
    cm, q = _chain_mock([_row(1)])
    with patch("app.routes.timeline.get_supabase_client", return_value=cm):
        client.get("/timeline?domains=task,food", headers=_auth())
    q.in_.assert_called_once_with("domain", ["task", "food"])


def test_no_domain_filter_when_absent():
    cm, q = _chain_mock([_row(1)])
    with patch("app.routes.timeline.get_supabase_client", return_value=cm):
        client.get("/timeline", headers=_auth())
    q.in_.assert_not_called()


def test_invalid_domain_returns_422():
    res = client.get("/timeline?domains=task,bogus", headers=_auth())
    assert res.status_code == 422


def test_habit_and_goal_are_accepted_domains():
    cm, q = _chain_mock([_row(1, domain="habit")])
    with patch("app.routes.timeline.get_supabase_client", return_value=cm):
        res = client.get("/timeline?domains=habit,goal", headers=_auth())
    assert res.status_code == 200
    q.in_.assert_called_once_with("domain", ["habit", "goal"])


def test_decision_is_accepted_domain():
    cm, q = _chain_mock([_row(1, domain="decision")])
    with patch("app.routes.timeline.get_supabase_client", return_value=cm):
        res = client.get("/timeline?domains=decision", headers=_auth())
    assert res.status_code == 200
    q.in_.assert_called_once_with("domain", ["decision"])


def test_date_filters_applied():
    cm, q = _chain_mock([_row(1)])
    with patch("app.routes.timeline.get_supabase_client", return_value=cm):
        client.get(
            "/timeline?from=2026-06-01T00:00:00Z&to=2026-06-30T00:00:00Z", headers=_auth()
        )
    assert q.gte.call_args.args[0] == "occurred_at"
    assert q.lt.call_args.args[0] == "occurred_at"


def test_invalid_from_returns_422():
    res = client.get("/timeline?from=notadate", headers=_auth())
    assert res.status_code == 422


def test_limit_out_of_range_returns_422():
    assert client.get("/timeline?limit=0", headers=_auth()).status_code == 422
    assert client.get("/timeline?limit=201", headers=_auth()).status_code == 422


# --- pagination ---


def test_next_cursor_present_when_more_rows():
    # limit=2 → fetch 3; returning 3 rows means there is another page.
    rows = [_row(1), _row(2), _row(3)]
    cm, q = _chain_mock(rows)
    with patch("app.routes.timeline.get_supabase_client", return_value=cm):
        res = client.get("/timeline?limit=2", headers=_auth())
    body = res.json()
    assert len(body["items"]) == 2
    assert body["next_cursor"] is not None
    q.limit.assert_called_once_with(3)


def test_no_next_cursor_when_no_more_rows():
    rows = [_row(1), _row(2)]
    cm, _ = _chain_mock(rows)
    with patch("app.routes.timeline.get_supabase_client", return_value=cm):
        res = client.get("/timeline?limit=2", headers=_auth())
    assert res.json()["next_cursor"] is None


def test_cursor_applies_keyset_filter():
    cursor = base64.urlsafe_b64encode(b"2026-06-20T10:00:00+00:00|evt-1").decode()
    cm, q = _chain_mock([_row(1)])
    with patch("app.routes.timeline.get_supabase_client", return_value=cm):
        client.get(f"/timeline?cursor={cursor}", headers=_auth())
    q.or_.assert_called_once()
    arg = q.or_.call_args.args[0]
    assert "occurred_at.lt." in arg and "id.lt." in arg


def test_malformed_cursor_returns_422():
    # valid base64 but no pipe separator
    bad = base64.urlsafe_b64encode(b"nopipe").decode()
    assert client.get(f"/timeline?cursor={bad}", headers=_auth()).status_code == 422
    # not even base64
    assert client.get("/timeline?cursor=%%%", headers=_auth()).status_code == 422


# --- read-only guard ---


def test_route_never_writes():
    cm, q = _chain_mock([_row(1)])
    with patch("app.routes.timeline.get_supabase_client", return_value=cm):
        client.get("/timeline", headers=_auth())
    cm.rpc.assert_not_called()
    q.insert.assert_not_called()
    q.update.assert_not_called()
    q.delete.assert_not_called()


# --- errors ---


def test_db_config_error_returns_500():
    with patch(
        "app.routes.timeline.get_supabase_client",
        side_effect=SupabaseConfigurationError("missing key"),
    ):
        res = client.get("/timeline", headers=_auth())
    assert res.status_code == 500


def test_query_failure_returns_503():
    q = MagicMock()
    for method in ("select", "order", "in_", "gte", "lt", "or_", "limit"):
        getattr(q, method).return_value = q
    q.execute.side_effect = Exception("connection refused")
    cm = MagicMock()
    cm.table.return_value = q
    with patch("app.routes.timeline.get_supabase_client", return_value=cm):
        res = client.get("/timeline", headers=_auth())
    assert res.status_code == 503
