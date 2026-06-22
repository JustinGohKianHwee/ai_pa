"""
Tests for PATCH /inbox/{id}/confirm, PATCH /inbox/{id}/reject, PATCH /inbox/{id} (edit).

Phase 7 review actions: mark inbox items confirmed/rejected, or correct their fields.
No domain records are ever created — these endpoints only touch inbox_items.
"""
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.db.supabase_client import SupabaseConfigurationError
from app.main import app

client = TestClient(app)

from tests.conftest import mint_test_token

VALID_TOKEN = mint_test_token()
INBOX_ID = "inbox-uuid-phase7"

# ---------------------------------------------------------------------------
# Sample rows
# ---------------------------------------------------------------------------

PENDING_FINANCE_ROW = {
    "id": INBOX_ID,
    "item_type": "finance",
    "review_status": "pending",
    "title": "Lunch",
    "body": "Spent $12",
    "confidence": 0.9,
    "reviewed_at": None,
    "updated_at": "2024-01-01T12:00:00+00:00",
    "structured_json": {"amount": 12.0, "currency": "SGD", "direction": "expense"},
}

PENDING_UNKNOWN_ROW = {
    **PENDING_FINANCE_ROW,
    "item_type": "unknown",
    "structured_json": {},
}

NEEDS_MANUAL_ROW = {
    **PENDING_FINANCE_ROW,
    "review_status": "needs_manual_classification",
    "item_type": "unknown",
    "structured_json": {},
}

CONFIRMED_ROW = {
    **PENDING_FINANCE_ROW,
    "review_status": "confirmed",
    "reviewed_at": "2024-01-01T13:00:00+00:00",
}

REJECTED_ROW = {
    **PENDING_FINANCE_ROW,
    "review_status": "rejected",
    "reviewed_at": "2024-01-01T13:00:00+00:00",
}

# Finance INCOME items are out of scope for Phase 9 domain records: they confirm via the
# Phase 7 status-only path (no money_event). These rows exercise that path.
PENDING_INCOME_ROW = {
    **PENDING_FINANCE_ROW,
    "title": "Salary",
    "body": "got paid 3000 salary",
    "structured_json": {"amount": 3000.0, "currency": "SGD", "direction": "income"},
}

CONFIRMED_INCOME_ROW = {
    **PENDING_INCOME_ROW,
    "review_status": "confirmed",
    "reviewed_at": "2024-01-01T13:00:00+00:00",
}


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

def _auth_header(token: str = VALID_TOKEN) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _make_confirm_mock(fetch_data: list, update_data: list) -> MagicMock:
    """
    Confirm uses: select→eq→execute (fetch), then update→eq→eq→eq→execute (update).
    """
    mock = MagicMock()
    mock.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
        data=fetch_data
    )
    (
        mock.table.return_value
        .update.return_value
        .eq.return_value
        .eq.return_value
        .eq.return_value
        .execute.return_value
    ) = MagicMock(data=update_data)
    return mock


def _make_reject_edit_mock(fetch_data: list, update_data: list) -> MagicMock:
    """
    Reject and edit use: select→eq→execute (fetch), then update→eq→in_→execute (update).
    """
    mock = MagicMock()
    mock.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
        data=fetch_data
    )
    (
        mock.table.return_value
        .update.return_value
        .eq.return_value
        .in_.return_value
        .execute.return_value
    ) = MagicMock(data=update_data)
    return mock


def _make_confirm_concurrent_mock(first_fetch: list, second_fetch: list) -> MagicMock:
    """
    Simulates: first fetch→PENDING, update→[] (conflict), refetch→<second_fetch>.
    """
    mock = MagicMock()
    mock.table.return_value.select.return_value.eq.return_value.execute.side_effect = [
        MagicMock(data=first_fetch),
        MagicMock(data=second_fetch),
    ]
    (
        mock.table.return_value
        .update.return_value
        .eq.return_value
        .eq.return_value
        .eq.return_value
        .execute.return_value
    ) = MagicMock(data=[])
    return mock


def _make_edit_concurrent_mock(first_fetch: list, second_fetch: list) -> MagicMock:
    """
    Simulates: first fetch→PENDING, update→[] (conflict), refetch→<second_fetch>.
    """
    mock = MagicMock()
    mock.table.return_value.select.return_value.eq.return_value.execute.side_effect = [
        MagicMock(data=first_fetch),
        MagicMock(data=second_fetch),
    ]
    (
        mock.table.return_value
        .update.return_value
        .eq.return_value
        .in_.return_value
        .execute.return_value
    ) = MagicMock(data=[])
    return mock


# ---------------------------------------------------------------------------
# Confirm — auth guard
# ---------------------------------------------------------------------------


def test_confirm_missing_token_returns_401(monkeypatch):
    response = client.patch(f"/inbox/{INBOX_ID}/confirm")
    assert response.status_code == 401


def test_confirm_wrong_token_returns_401(monkeypatch):
    response = client.patch(
        f"/inbox/{INBOX_ID}/confirm", headers={"Authorization": "Bearer wrong-token"}
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Confirm — not found
# ---------------------------------------------------------------------------


def test_confirm_missing_item_returns_404(monkeypatch):
    mock = _make_confirm_mock(fetch_data=[], update_data=[])
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Confirm — happy path
# ---------------------------------------------------------------------------


def test_confirm_income_item_status_only_returns_200(monkeypatch):
    """A non-module item (finance income) confirms status-only — no domain record."""
    mock = _make_confirm_mock(
        fetch_data=[PENDING_INCOME_ROW], update_data=[CONFIRMED_INCOME_ROW]
    )
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.status_code == 200
    body = response.json()
    assert body["review_status"] == "confirmed"
    assert body["id"] == INBOX_ID
    assert "money_event" not in body  # status-only — no domain record
    mock.rpc.assert_not_called()


def test_confirm_sets_reviewed_at(monkeypatch):
    mock = _make_confirm_mock(
        fetch_data=[PENDING_INCOME_ROW], update_data=[CONFIRMED_INCOME_ROW]
    )
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.status_code == 200
    assert response.json()["reviewed_at"] is not None


def test_confirm_stores_normalized_structured_json(monkeypatch):
    """Status-only confirm stores the Pydantic-normalized form so currency='SGD' is persisted."""
    row_no_currency = {
        **PENDING_INCOME_ROW,
        "structured_json": {"amount": 3000.0, "direction": "income"},  # missing currency
    }
    confirmed_normalized = {
        **CONFIRMED_INCOME_ROW,
        "structured_json": {"amount": 3000.0, "direction": "income", "currency": "SGD"},
    }
    mock = _make_confirm_mock(fetch_data=[row_no_currency], update_data=[confirmed_normalized])
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.status_code == 200
    # Verify the update call received the normalized dict with currency default
    update_payload = mock.table.return_value.update.call_args[0][0]
    assert update_payload["structured_json"]["currency"] == "SGD"


# ---------------------------------------------------------------------------
# Confirm — invalid states
# ---------------------------------------------------------------------------


def test_confirm_unknown_item_type_returns_400(monkeypatch):
    mock = _make_confirm_mock(fetch_data=[PENDING_UNKNOWN_ROW], update_data=[])
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.status_code == 400
    assert "unknown" in response.json()["detail"].lower()


def test_confirm_needs_manual_returns_409(monkeypatch):
    mock = _make_confirm_mock(fetch_data=[NEEDS_MANUAL_ROW], update_data=[])
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.status_code == 409


def test_confirm_rejected_item_returns_409(monkeypatch):
    mock = _make_confirm_mock(fetch_data=[REJECTED_ROW], update_data=[])
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.status_code == 409


# ---------------------------------------------------------------------------
# Confirm — idempotency and concurrency
# ---------------------------------------------------------------------------


def test_confirm_already_confirmed_is_idempotent_200(monkeypatch):
    mock = _make_confirm_mock(fetch_data=[CONFIRMED_INCOME_ROW], update_data=[])
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.status_code == 200
    assert response.json()["review_status"] == "confirmed"


def test_confirm_concurrent_modification_treated_as_idempotent(monkeypatch):
    """
    If the conditional update (guarded by updated_at) returns 0 rows but a refetch
    shows the item is already confirmed, return 200 rather than 409.
    """
    mock = _make_confirm_concurrent_mock(
        first_fetch=[PENDING_INCOME_ROW],
        second_fetch=[CONFIRMED_INCOME_ROW],
    )
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.status_code == 200
    assert response.json()["review_status"] == "confirmed"


def test_confirm_creates_no_domain_record(monkeypatch):
    """Status-only confirm touches only inbox_items — never a domain table or the RPC."""
    mock = _make_confirm_mock(
        fetch_data=[PENDING_INCOME_ROW], update_data=[CONFIRMED_INCOME_ROW]
    )
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    domain_tables = {"tasks", "money_events", "food_logs", "calendar_intents", "investment_notes"}
    touched = {call[0][0] for call in mock.table.call_args_list}
    assert touched.isdisjoint(domain_tables)
    mock.rpc.assert_not_called()


# ---------------------------------------------------------------------------
# Confirm — database errors
# ---------------------------------------------------------------------------


def test_confirm_db_config_error_returns_500(monkeypatch):
    with patch(
        "app.routes.review.get_supabase_client",
        side_effect=SupabaseConfigurationError("missing key"),
    ):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.status_code == 500


def test_confirm_db_query_failure_returns_503(monkeypatch):
    mock = MagicMock()
    mock.table.return_value.select.return_value.eq.return_value.execute.side_effect = Exception(
        "connection refused"
    )
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.status_code == 503


# ===========================================================================
# Reject
# ===========================================================================


def test_reject_missing_token_returns_401(monkeypatch):
    response = client.patch(f"/inbox/{INBOX_ID}/reject")
    assert response.status_code == 401


def test_reject_wrong_token_returns_401(monkeypatch):
    response = client.patch(
        f"/inbox/{INBOX_ID}/reject", headers={"Authorization": "Bearer wrong-token"}
    )
    assert response.status_code == 401


def test_reject_pending_item_returns_200_rejected(monkeypatch):
    mock = _make_reject_edit_mock(fetch_data=[PENDING_FINANCE_ROW], update_data=[REJECTED_ROW])
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/reject", headers=_auth_header())
    assert response.status_code == 200
    assert response.json()["review_status"] == "rejected"


def test_reject_needs_manual_item_returns_200_rejected(monkeypatch):
    needs_manual_rejected = {**REJECTED_ROW, "item_type": "unknown", "structured_json": {}}
    mock = _make_reject_edit_mock(
        fetch_data=[NEEDS_MANUAL_ROW], update_data=[needs_manual_rejected]
    )
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/reject", headers=_auth_header())
    assert response.status_code == 200
    assert response.json()["review_status"] == "rejected"


def test_reject_already_rejected_is_idempotent_200(monkeypatch):
    mock = _make_reject_edit_mock(fetch_data=[REJECTED_ROW], update_data=[])
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/reject", headers=_auth_header())
    assert response.status_code == 200
    assert response.json()["review_status"] == "rejected"


def test_reject_confirmed_item_returns_409(monkeypatch):
    mock = _make_reject_edit_mock(fetch_data=[CONFIRMED_ROW], update_data=[])
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/reject", headers=_auth_header())
    assert response.status_code == 409


def test_reject_missing_item_returns_404(monkeypatch):
    mock = _make_reject_edit_mock(fetch_data=[], update_data=[])
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/reject", headers=_auth_header())
    assert response.status_code == 404


def test_reject_db_config_error_returns_500(monkeypatch):
    with patch(
        "app.routes.review.get_supabase_client",
        side_effect=SupabaseConfigurationError("missing"),
    ):
        response = client.patch(f"/inbox/{INBOX_ID}/reject", headers=_auth_header())
    assert response.status_code == 500


# ===========================================================================
# Edit
# ===========================================================================


def test_edit_missing_token_returns_401(monkeypatch):
    response = client.patch(f"/inbox/{INBOX_ID}", json={"title": "Updated"})
    assert response.status_code == 401


def test_edit_wrong_token_returns_401(monkeypatch):
    response = client.patch(
        f"/inbox/{INBOX_ID}",
        json={"title": "Updated"},
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert response.status_code == 401


def test_edit_pending_item_returns_200(monkeypatch):
    updated_row = {**PENDING_FINANCE_ROW, "title": "Updated title"}
    mock = _make_reject_edit_mock(fetch_data=[PENDING_FINANCE_ROW], update_data=[updated_row])
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(
            f"/inbox/{INBOX_ID}",
            json={"title": "Updated title"},
            headers=_auth_header(),
        )
    assert response.status_code == 200
    assert response.json()["title"] == "Updated title"


def test_edit_confirmed_item_returns_409(monkeypatch):
    mock = _make_reject_edit_mock(fetch_data=[CONFIRMED_ROW], update_data=[])
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(
            f"/inbox/{INBOX_ID}", json={"title": "x"}, headers=_auth_header()
        )
    assert response.status_code == 409


def test_edit_rejected_item_returns_409(monkeypatch):
    mock = _make_reject_edit_mock(fetch_data=[REJECTED_ROW], update_data=[])
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(
            f"/inbox/{INBOX_ID}", json={"title": "x"}, headers=_auth_header()
        )
    assert response.status_code == 409


def test_edit_invalid_item_type_returns_400(monkeypatch):
    mock = _make_reject_edit_mock(fetch_data=[PENDING_FINANCE_ROW], update_data=[])
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(
            f"/inbox/{INBOX_ID}",
            json={"item_type": "grocery"},  # not a valid type
            headers=_auth_header(),
        )
    assert response.status_code == 400
    assert "grocery" in response.json()["detail"]


def test_edit_invalid_structured_json_returns_400(monkeypatch):
    mock = _make_reject_edit_mock(fetch_data=[PENDING_FINANCE_ROW], update_data=[])
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(
            f"/inbox/{INBOX_ID}",
            # finance requires amount + direction; this is missing both
            json={"structured_json": {"merchant": "Starbucks"}},
            headers=_auth_header(),
        )
    assert response.status_code == 400


def test_edit_needs_manual_with_valid_type_returns_pending(monkeypatch):
    """Correcting a needs_manual item to a valid type clears it to pending."""
    corrected_row = {
        **NEEDS_MANUAL_ROW,
        "item_type": "finance",
        "review_status": "pending",
        "structured_json": {"amount": 12.0, "currency": "SGD", "direction": "expense"},
    }
    mock = _make_reject_edit_mock(fetch_data=[NEEDS_MANUAL_ROW], update_data=[corrected_row])
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(
            f"/inbox/{INBOX_ID}",
            json={
                "item_type": "finance",
                "structured_json": {"amount": 12.0, "direction": "expense"},
            },
            headers=_auth_header(),
        )
    assert response.status_code == 200
    # Verify the update patch set review_status="pending"
    update_payload = mock.table.return_value.update.call_args[0][0]
    assert update_payload["review_status"] == "pending"


def test_edit_setting_unknown_type_remains_needs_manual(monkeypatch):
    """
    Setting item_type='unknown' (on a pending item) must produce needs_manual_classification,
    never pending. This prevents accidentally re-introducing a confirmable unknown item.
    """
    needs_manual_result = {**PENDING_FINANCE_ROW, "item_type": "unknown", "review_status": "needs_manual_classification", "structured_json": {}}
    mock = _make_reject_edit_mock(fetch_data=[PENDING_FINANCE_ROW], update_data=[needs_manual_result])
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(
            f"/inbox/{INBOX_ID}",
            json={"item_type": "unknown", "structured_json": {}},
            headers=_auth_header(),
        )
    assert response.status_code == 200
    update_payload = mock.table.return_value.update.call_args[0][0]
    assert update_payload["review_status"] == "needs_manual_classification"


def test_edit_stores_normalized_structured_json(monkeypatch):
    """Edit must persist normalized JSON so defaults like currency='SGD' are retained."""
    updated_row = {
        **PENDING_FINANCE_ROW,
        "structured_json": {"amount": 20.0, "direction": "expense", "currency": "SGD"},
    }
    mock = _make_reject_edit_mock(fetch_data=[PENDING_FINANCE_ROW], update_data=[updated_row])
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(
            f"/inbox/{INBOX_ID}",
            json={"structured_json": {"amount": 20.0, "direction": "expense"}},  # no currency
            headers=_auth_header(),
        )
    assert response.status_code == 200
    update_payload = mock.table.return_value.update.call_args[0][0]
    assert update_payload["structured_json"]["currency"] == "SGD"


def test_edit_state_conditional_update_blocks_confirmed_race(monkeypatch):
    """
    If a concurrent confirm/reject lands between our fetch and our update,
    the state-conditional .in_() guard returns 0 rows. We refetch and return 409.
    """
    mock = _make_edit_concurrent_mock(
        first_fetch=[PENDING_FINANCE_ROW],
        second_fetch=[CONFIRMED_ROW],
    )
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(
            f"/inbox/{INBOX_ID}",
            json={"title": "Too late"},
            headers=_auth_header(),
        )
    assert response.status_code == 409


def test_edit_does_not_call_openai(monkeypatch):
    """Edit never calls OpenAI — OPENAI_API_KEY absent must not affect the result."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    updated_row = {**PENDING_FINANCE_ROW, "title": "New title"}
    mock = _make_reject_edit_mock(fetch_data=[PENDING_FINANCE_ROW], update_data=[updated_row])
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(
            f"/inbox/{INBOX_ID}",
            json={"title": "New title"},
            headers=_auth_header(),
        )
    assert response.status_code == 200


def test_edit_db_config_error_returns_500(monkeypatch):
    with patch(
        "app.routes.review.get_supabase_client",
        side_effect=SupabaseConfigurationError("missing"),
    ):
        response = client.patch(
            f"/inbox/{INBOX_ID}", json={"title": "x"}, headers=_auth_header()
        )
    assert response.status_code == 500


# ===========================================================================
# Phase 8 — task confirmation (atomic confirm + task via RPC)
# ===========================================================================

PENDING_TASK_ROW = {
    "id": INBOX_ID,
    "item_type": "task",
    "review_status": "pending",
    "title": "Pay credit card bill",
    "body": "remind me to pay the credit card bill next Friday",
    "confidence": 0.92,
    "reviewed_at": None,
    "updated_at": "2024-01-01T12:00:00+00:00",
    "structured_json": {"due_date": "next Friday", "urgency": "this_week"},
}

CONFIRMED_TASK_ITEM = {
    **PENDING_TASK_ROW,
    "review_status": "confirmed",
    "reviewed_at": "2024-01-01T12:05:00+00:00",
}

TASK_ROW = {
    "id": "task-uuid-1",
    "inbox_item_id": INBOX_ID,
    "title": "Pay credit card bill",
    "urgency": "this_week",
    "due_date": "next Friday",
    "notes": None,
    "status": "open",
    "completed_at": None,
    "created_at": "2024-01-01T12:05:00+00:00",
    "updated_at": "2024-01-01T12:05:00+00:00",
}

RPC_RESULT = {"inbox_item": CONFIRMED_TASK_ITEM, "task": TASK_ROW}

DOMAIN_TABLES = {"tasks", "money_events", "food_logs", "calendar_intents", "investment_notes"}


def _make_task_confirm_mock(
    inbox_results: list,
    tasks_results: list | None = None,
    rpc_result=None,
    rpc_error: bool = False,
) -> MagicMock:
    """
    Builds a Supabase client mock that routes .table('inbox_items') and
    .table('tasks') to separate sub-mocks and stubs .rpc(...).execute().

    inbox_results / tasks_results are lists of `data` payloads returned by
    successive .select(...).eq(...).execute() calls on each table.
    """
    client_mock = MagicMock()

    inbox_tbl = MagicMock()
    inbox_tbl.select.return_value.eq.return_value.execute.side_effect = [
        MagicMock(data=d) for d in inbox_results
    ]

    tasks_tbl = MagicMock()
    tasks_tbl.select.return_value.eq.return_value.execute.side_effect = [
        MagicMock(data=d) for d in (tasks_results or [])
    ]

    client_mock.table.side_effect = lambda name: tasks_tbl if name == "tasks" else inbox_tbl

    if rpc_error:
        client_mock.rpc.return_value.execute.side_effect = Exception("rpc failed")
    else:
        client_mock.rpc.return_value.execute.return_value = MagicMock(data=rpc_result)

    return client_mock


def test_confirm_pending_task_creates_task_and_confirms(monkeypatch):
    mock = _make_task_confirm_mock(inbox_results=[[PENDING_TASK_ROW]], rpc_result=RPC_RESULT)
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.status_code == 200
    body = response.json()
    assert body["inbox_item"]["review_status"] == "confirmed"
    assert body["task"]["id"] == "task-uuid-1"
    # The RPC is the single writer — exactly one call, with the concurrency guard.
    mock.rpc.assert_called_once_with(
        "confirm_task_item",
        {"p_inbox_id": INBOX_ID, "p_expected_updated_at": "2024-01-01T12:00:00+00:00"},
    )


def test_confirm_task_records_reviewed_at(monkeypatch):
    mock = _make_task_confirm_mock(inbox_results=[[PENDING_TASK_ROW]], rpc_result=RPC_RESULT)
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.status_code == 200
    assert response.json()["inbox_item"]["reviewed_at"] is not None


def test_confirm_task_links_correct_inbox_item_id(monkeypatch):
    mock = _make_task_confirm_mock(inbox_results=[[PENDING_TASK_ROW]], rpc_result=RPC_RESULT)
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.json()["task"]["inbox_item_id"] == INBOX_ID


def test_confirm_task_duplicate_returns_same_task(monkeypatch):
    """Confirming an already-confirmed task returns the existing task without a new RPC."""
    mock = _make_task_confirm_mock(
        inbox_results=[[CONFIRMED_TASK_ITEM]], tasks_results=[[TASK_ROW]]
    )
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.status_code == 200
    assert response.json()["task"]["id"] == "task-uuid-1"
    mock.rpc.assert_not_called()


def test_confirm_task_concurrent_creates_at_most_one(monkeypatch):
    """
    If the RPC raises mid-race but the item ends up confirmed with a task,
    the result is idempotent success — no second task.
    """
    mock = _make_task_confirm_mock(
        inbox_results=[[PENDING_TASK_ROW], [CONFIRMED_TASK_ITEM]],
        tasks_results=[[TASK_ROW]],
        rpc_error=True,
    )
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.status_code == 200
    assert response.json()["task"]["id"] == "task-uuid-1"


def test_confirm_task_rpc_failure_unchanged_pending_returns_503(monkeypatch):
    """RPC raised, item still pending with the same updated_at and no task → nothing
    committed → 503 (a database failure, not a concurrency conflict)."""
    mock = _make_task_confirm_mock(
        inbox_results=[[PENDING_TASK_ROW], [PENDING_TASK_ROW]],
        tasks_results=[[]],
        rpc_error=True,
    )
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.status_code == 503
    # The safe message must not leak the raw DB exception.
    assert response.json()["detail"] == "Task confirmation database operation failed"


def test_confirm_task_rpc_exception_with_changed_state_returns_409(monkeypatch):
    """RPC raised and the inbox row changed from the validated snapshot (updated_at
    moved) with no task → another writer won the race → 409."""
    changed = {**PENDING_TASK_ROW, "updated_at": "2024-01-01T13:30:00+00:00"}
    mock = _make_task_confirm_mock(
        inbox_results=[[PENDING_TASK_ROW], [changed]],
        tasks_results=[[]],
        rpc_error=True,
    )
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.status_code == 409


def test_confirm_task_does_not_insert_task_in_python(monkeypatch):
    """The task is created only by the RPC — never by a Python .insert on the tasks table."""
    mock = _make_task_confirm_mock(inbox_results=[[PENDING_TASK_ROW]], rpc_result=RPC_RESULT)
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.status_code == 200
    mock.rpc.assert_called_once()
    mock.table("tasks").insert.assert_not_called()
    mock.table("inbox_items").insert.assert_not_called()


def test_confirm_already_confirmed_task_without_task_not_backfilled(monkeypatch):
    """A Phase 7 task item confirmed before the tasks table existed is not backfilled."""
    mock = _make_task_confirm_mock(
        inbox_results=[[CONFIRMED_TASK_ITEM]], tasks_results=[[]]
    )
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.status_code == 409
    mock.rpc.assert_not_called()


def test_confirm_task_invalid_structured_json_creates_no_task(monkeypatch):
    bad_item = {**PENDING_TASK_ROW, "structured_json": {"urgency": "asap"}}  # invalid literal
    mock = _make_task_confirm_mock(inbox_results=[[bad_item]])
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.status_code == 400
    mock.rpc.assert_not_called()


def test_confirm_task_missing_title_creates_no_task(monkeypatch):
    no_title = {**PENDING_TASK_ROW, "title": "", "structured_json": {"urgency": "today"}}
    mock = _make_task_confirm_mock(inbox_results=[[no_title]])
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.status_code == 400
    mock.rpc.assert_not_called()


def test_confirm_rejected_task_creates_no_task(monkeypatch):
    rejected_task = {
        **PENDING_TASK_ROW,
        "review_status": "rejected",
        "reviewed_at": "2024-01-01T13:00:00+00:00",
    }
    mock = _make_task_confirm_mock(inbox_results=[[rejected_task]])
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.status_code == 409
    mock.rpc.assert_not_called()


def test_confirm_task_touches_no_other_domain_tables(monkeypatch):
    mock = _make_task_confirm_mock(inbox_results=[[PENDING_TASK_ROW]], rpc_result=RPC_RESULT)
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    touched = {call.args[0] for call in mock.table.call_args_list}
    assert touched.isdisjoint(DOMAIN_TABLES - {"tasks"})
    # The RPC named is the task confirmation function only.
    assert mock.rpc.call_args.args[0] == "confirm_task_item"


# ===========================================================================
# Phase 9 — finance EXPENSE confirmation (atomic confirm + money_event via RPC)
# ===========================================================================

MONEY_EVENT_ROW = {
    "id": "money-uuid-1",
    "inbox_item_id": INBOX_ID,
    "amount": 12.0,
    "currency": "SGD",
    "direction": "expense",
    "merchant": None,
    "category": "food",
    "occurred_at": None,
    "notes": None,
    "created_at": "2024-01-01T12:05:00+00:00",
}

FINANCE_RPC_RESULT = {"inbox_item": CONFIRMED_ROW, "money_event": MONEY_EVENT_ROW}


def _make_finance_confirm_mock(
    inbox_results: list,
    money_results: list | None = None,
    rpc_result=None,
    rpc_error: bool = False,
) -> MagicMock:
    """
    Routes .table('inbox_items') and .table('money_events') to separate sub-mocks and
    stubs .rpc(...).execute(), mirroring _make_task_confirm_mock.
    """
    client_mock = MagicMock()

    inbox_tbl = MagicMock()
    inbox_tbl.select.return_value.eq.return_value.execute.side_effect = [
        MagicMock(data=d) for d in inbox_results
    ]

    money_tbl = MagicMock()
    money_tbl.select.return_value.eq.return_value.execute.side_effect = [
        MagicMock(data=d) for d in (money_results or [])
    ]

    client_mock.table.side_effect = (
        lambda name: money_tbl if name == "money_events" else inbox_tbl
    )

    if rpc_error:
        client_mock.rpc.return_value.execute.side_effect = Exception("rpc failed")
    else:
        client_mock.rpc.return_value.execute.return_value = MagicMock(data=rpc_result)

    return client_mock


def test_confirm_pending_expense_creates_money_event_and_confirms(monkeypatch):
    mock = _make_finance_confirm_mock(
        inbox_results=[[PENDING_FINANCE_ROW]], rpc_result=FINANCE_RPC_RESULT
    )
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.status_code == 200
    body = response.json()
    assert body["inbox_item"]["review_status"] == "confirmed"
    assert body["money_event"]["id"] == "money-uuid-1"
    mock.rpc.assert_called_once_with(
        "confirm_finance_item",
        {"p_inbox_id": INBOX_ID, "p_expected_updated_at": "2024-01-01T12:00:00+00:00"},
    )


def test_confirm_expense_records_reviewed_at(monkeypatch):
    mock = _make_finance_confirm_mock(
        inbox_results=[[PENDING_FINANCE_ROW]], rpc_result=FINANCE_RPC_RESULT
    )
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.json()["inbox_item"]["reviewed_at"] is not None


def test_confirm_expense_links_correct_inbox_item_id(monkeypatch):
    mock = _make_finance_confirm_mock(
        inbox_results=[[PENDING_FINANCE_ROW]], rpc_result=FINANCE_RPC_RESULT
    )
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.json()["money_event"]["inbox_item_id"] == INBOX_ID


def test_confirm_expense_duplicate_returns_same_event(monkeypatch):
    mock = _make_finance_confirm_mock(
        inbox_results=[[CONFIRMED_ROW]], money_results=[[MONEY_EVENT_ROW]]
    )
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.status_code == 200
    assert response.json()["money_event"]["id"] == "money-uuid-1"
    mock.rpc.assert_not_called()


def test_confirm_expense_concurrent_creates_at_most_one(monkeypatch):
    mock = _make_finance_confirm_mock(
        inbox_results=[[PENDING_FINANCE_ROW], [CONFIRMED_ROW]],
        money_results=[[MONEY_EVENT_ROW]],
        rpc_error=True,
    )
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.status_code == 200
    assert response.json()["money_event"]["id"] == "money-uuid-1"


def test_confirm_expense_rpc_failure_unchanged_pending_returns_503(monkeypatch):
    mock = _make_finance_confirm_mock(
        inbox_results=[[PENDING_FINANCE_ROW], [PENDING_FINANCE_ROW]],
        money_results=[[]],
        rpc_error=True,
    )
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.status_code == 503
    assert response.json()["detail"] == "Finance confirmation database operation failed"


def test_confirm_expense_rpc_exception_with_changed_state_returns_409(monkeypatch):
    changed = {**PENDING_FINANCE_ROW, "updated_at": "2024-01-01T13:30:00+00:00"}
    mock = _make_finance_confirm_mock(
        inbox_results=[[PENDING_FINANCE_ROW], [changed]],
        money_results=[[]],
        rpc_error=True,
    )
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.status_code == 409


def test_confirm_already_confirmed_expense_without_event_not_backfilled(monkeypatch):
    """A finance expense confirmed before the money_events module existed is not backfilled."""
    mock = _make_finance_confirm_mock(
        inbox_results=[[CONFIRMED_ROW]], money_results=[[]]
    )
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.status_code == 409
    mock.rpc.assert_not_called()


def test_confirm_expense_invalid_structured_json_creates_no_event(monkeypatch):
    bad = {**PENDING_FINANCE_ROW, "structured_json": {"currency": "SGD", "direction": "expense"}}
    mock = _make_finance_confirm_mock(inbox_results=[[bad]])
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.status_code == 400
    mock.rpc.assert_not_called()


def test_confirm_expense_zero_amount_creates_no_event(monkeypatch):
    zero = {
        **PENDING_FINANCE_ROW,
        "structured_json": {"amount": 0, "currency": "SGD", "direction": "expense"},
    }
    mock = _make_finance_confirm_mock(inbox_results=[[zero]])
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.status_code == 400
    mock.rpc.assert_not_called()


def test_confirm_finance_invalid_direction_returns_400(monkeypatch):
    """An invalid direction is not 'expense', so it routes to status-only, which rejects it."""
    bad = {**PENDING_FINANCE_ROW, "structured_json": {"amount": 12.0, "currency": "SGD", "direction": "refund"}}
    mock = _make_confirm_mock(fetch_data=[bad], update_data=[])
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.status_code == 400
    mock.rpc.assert_not_called()


def test_confirm_expense_does_not_insert_in_python(monkeypatch):
    """The money_event is created only by the RPC — never by a Python .insert."""
    mock = _make_finance_confirm_mock(
        inbox_results=[[PENDING_FINANCE_ROW]], rpc_result=FINANCE_RPC_RESULT
    )
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.status_code == 200
    mock.rpc.assert_called_once()
    mock.table("money_events").insert.assert_not_called()
    mock.table("inbox_items").insert.assert_not_called()


def test_confirm_expense_touches_no_other_domain_tables(monkeypatch):
    mock = _make_finance_confirm_mock(
        inbox_results=[[PENDING_FINANCE_ROW]], rpc_result=FINANCE_RPC_RESULT
    )
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    touched = {call.args[0] for call in mock.table.call_args_list}
    assert touched.isdisjoint(DOMAIN_TABLES - {"money_events"})
    assert mock.rpc.call_args.args[0] == "confirm_finance_item"


def test_confirm_task_path_unchanged_by_finance(monkeypatch):
    """Task confirmation still routes to confirm_task_item, not the finance RPC."""
    mock = _make_task_confirm_mock(inbox_results=[[PENDING_TASK_ROW]], rpc_result=RPC_RESULT)
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.status_code == 200
    assert response.json()["task"]["id"] == "task-uuid-1"
    assert mock.rpc.call_args.args[0] == "confirm_task_item"


# ===========================================================================
# Phase 11 — food confirmation (atomic confirm + food_log via RPC)
# ===========================================================================

PENDING_FOOD_ROW = {
    "id": INBOX_ID,
    "item_type": "food",
    "review_status": "pending",
    "title": "Chicken rice for lunch",
    "body": "ate chicken rice for lunch",
    "confidence": 0.95,
    "reviewed_at": None,
    "updated_at": "2024-01-01T12:00:00+00:00",
    "structured_json": {"description": "chicken rice", "meal_type": "lunch"},
}

CONFIRMED_FOOD_ITEM = {
    **PENDING_FOOD_ROW,
    "review_status": "confirmed",
    "reviewed_at": "2024-01-01T12:05:00+00:00",
}

FOOD_LOG_ROW = {
    "id": "food-log-uuid-1",
    "inbox_item_id": INBOX_ID,
    "description": "chicken rice",
    "meal_type": "lunch",
    "logged_at": None,
    "created_at": "2024-01-01T12:05:00+00:00",
}

FOOD_RPC_RESULT = {"inbox_item": CONFIRMED_FOOD_ITEM, "food_log": FOOD_LOG_ROW}


def _make_food_confirm_mock(
    inbox_results: list,
    food_log_results: list | None = None,
    rpc_result=None,
    rpc_error: bool = False,
) -> MagicMock:
    """
    Routes .table('inbox_items') and .table('food_logs') to separate sub-mocks and
    stubs .rpc(...).execute(), mirroring _make_finance_confirm_mock.
    """
    client_mock = MagicMock()

    inbox_tbl = MagicMock()
    inbox_tbl.select.return_value.eq.return_value.execute.side_effect = [
        MagicMock(data=d) for d in inbox_results
    ]

    food_tbl = MagicMock()
    food_tbl.select.return_value.eq.return_value.execute.side_effect = [
        MagicMock(data=d) for d in (food_log_results or [])
    ]

    client_mock.table.side_effect = (
        lambda name: food_tbl if name == "food_logs" else inbox_tbl
    )

    if rpc_error:
        client_mock.rpc.return_value.execute.side_effect = Exception("rpc failed")
    else:
        client_mock.rpc.return_value.execute.return_value = MagicMock(data=rpc_result)

    return client_mock


def test_confirm_pending_food_creates_food_log_and_confirms(monkeypatch):
    mock = _make_food_confirm_mock(
        inbox_results=[[PENDING_FOOD_ROW]], rpc_result=FOOD_RPC_RESULT
    )
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.status_code == 200
    body = response.json()
    assert body["inbox_item"]["review_status"] == "confirmed"
    assert body["food_log"]["id"] == "food-log-uuid-1"
    mock.rpc.assert_called_once_with(
        "confirm_food_item",
        {"p_inbox_id": INBOX_ID, "p_expected_updated_at": "2024-01-01T12:00:00+00:00"},
    )


def test_confirm_food_records_reviewed_at(monkeypatch):
    mock = _make_food_confirm_mock(
        inbox_results=[[PENDING_FOOD_ROW]], rpc_result=FOOD_RPC_RESULT
    )
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.json()["inbox_item"]["reviewed_at"] is not None


def test_confirm_food_links_correct_inbox_item_id(monkeypatch):
    mock = _make_food_confirm_mock(
        inbox_results=[[PENDING_FOOD_ROW]], rpc_result=FOOD_RPC_RESULT
    )
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.json()["food_log"]["inbox_item_id"] == INBOX_ID


def test_confirm_food_duplicate_returns_same_log(monkeypatch):
    """Confirming an already-confirmed food item returns the existing log without a new RPC."""
    mock = _make_food_confirm_mock(
        inbox_results=[[CONFIRMED_FOOD_ITEM]], food_log_results=[[FOOD_LOG_ROW]]
    )
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.status_code == 200
    assert response.json()["food_log"]["id"] == "food-log-uuid-1"
    mock.rpc.assert_not_called()


def test_confirm_food_concurrent_creates_at_most_one(monkeypatch):
    """If the RPC raises mid-race but the item ends up confirmed with a log, return 200."""
    mock = _make_food_confirm_mock(
        inbox_results=[[PENDING_FOOD_ROW], [CONFIRMED_FOOD_ITEM]],
        food_log_results=[[FOOD_LOG_ROW]],
        rpc_error=True,
    )
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.status_code == 200
    assert response.json()["food_log"]["id"] == "food-log-uuid-1"


def test_confirm_food_rpc_failure_unchanged_pending_returns_503(monkeypatch):
    """RPC raised, item still pending with same updated_at and no log → 503."""
    mock = _make_food_confirm_mock(
        inbox_results=[[PENDING_FOOD_ROW], [PENDING_FOOD_ROW]],
        food_log_results=[[]],
        rpc_error=True,
    )
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.status_code == 503
    assert response.json()["detail"] == "Food confirmation database operation failed"


def test_confirm_food_rpc_exception_with_changed_state_returns_409(monkeypatch):
    """RPC raised and updated_at changed → another writer won → 409."""
    changed = {**PENDING_FOOD_ROW, "updated_at": "2024-01-01T13:30:00+00:00"}
    mock = _make_food_confirm_mock(
        inbox_results=[[PENDING_FOOD_ROW], [changed]],
        food_log_results=[[]],
        rpc_error=True,
    )
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.status_code == 409


def test_confirm_already_confirmed_food_without_log_not_backfilled(monkeypatch):
    """A food item confirmed before the food module existed is not backfilled."""
    mock = _make_food_confirm_mock(
        inbox_results=[[CONFIRMED_FOOD_ITEM]], food_log_results=[[]]
    )
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.status_code == 409
    mock.rpc.assert_not_called()


def test_confirm_food_invalid_structured_json_creates_no_log(monkeypatch):
    """Missing required description → 400, RPC not called."""
    bad = {**PENDING_FOOD_ROW, "structured_json": {"meal_type": "lunch"}}  # no description
    mock = _make_food_confirm_mock(inbox_results=[[bad]])
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.status_code == 400
    mock.rpc.assert_not_called()


def test_confirm_food_whitespace_description_creates_no_log(monkeypatch):
    """Whitespace-only description passes Pydantic but is caught by explicit check → 400."""
    whitespace = {**PENDING_FOOD_ROW, "structured_json": {"description": "   "}}
    mock = _make_food_confirm_mock(inbox_results=[[whitespace]])
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.status_code == 400
    mock.rpc.assert_not_called()


def test_confirm_food_does_not_insert_in_python(monkeypatch):
    """The food_log is created only by the RPC — never by a Python .insert."""
    mock = _make_food_confirm_mock(
        inbox_results=[[PENDING_FOOD_ROW]], rpc_result=FOOD_RPC_RESULT
    )
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.status_code == 200
    mock.rpc.assert_called_once()
    mock.table("food_logs").insert.assert_not_called()
    mock.table("inbox_items").insert.assert_not_called()


def test_confirm_food_rpc_name_is_confirm_food_item(monkeypatch):
    """The RPC must be named exactly 'confirm_food_item'."""
    mock = _make_food_confirm_mock(
        inbox_results=[[PENDING_FOOD_ROW]], rpc_result=FOOD_RPC_RESULT
    )
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert mock.rpc.call_args.args[0] == "confirm_food_item"


def test_confirm_food_needs_manual_status_returns_409(monkeypatch):
    """A needs_manual_classification food item cannot be confirmed → 409."""
    needs_manual = {**PENDING_FOOD_ROW, "review_status": "needs_manual_classification"}
    mock = _make_food_confirm_mock(inbox_results=[[needs_manual]])
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.status_code == 409
    mock.rpc.assert_not_called()


# ===========================================================================
# Finance amount validation (Issue 3)
# ===========================================================================


def test_confirm_finance_nan_amount_returns_400(monkeypatch):
    nan_row = {
        **PENDING_FINANCE_ROW,
        "structured_json": {"amount": float("nan"), "currency": "SGD", "direction": "expense"},
    }
    mock = _make_finance_confirm_mock(inbox_results=[[nan_row]])
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.status_code == 400
    mock.rpc.assert_not_called()


def test_confirm_finance_positive_infinity_returns_400(monkeypatch):
    inf_row = {
        **PENDING_FINANCE_ROW,
        "structured_json": {"amount": float("inf"), "currency": "SGD", "direction": "expense"},
    }
    mock = _make_finance_confirm_mock(inbox_results=[[inf_row]])
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.status_code == 400
    mock.rpc.assert_not_called()


def test_confirm_finance_negative_infinity_returns_400(monkeypatch):
    neg_inf_row = {
        **PENDING_FINANCE_ROW,
        "structured_json": {"amount": float("-inf"), "currency": "SGD", "direction": "expense"},
    }
    mock = _make_finance_confirm_mock(inbox_results=[[neg_inf_row]])
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.status_code == 400
    mock.rpc.assert_not_called()


def test_confirm_finance_negative_amount_returns_400(monkeypatch):
    neg_row = {
        **PENDING_FINANCE_ROW,
        "structured_json": {"amount": -5.0, "currency": "SGD", "direction": "expense"},
    }
    mock = _make_finance_confirm_mock(inbox_results=[[neg_row]])
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.status_code == 400
    mock.rpc.assert_not_called()


def test_confirm_finance_valid_positive_amount_succeeds(monkeypatch):
    mock = _make_finance_confirm_mock(
        inbox_results=[[PENDING_FINANCE_ROW]], rpc_result=FINANCE_RPC_RESULT
    )
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.status_code == 200
    assert response.json()["money_event"]["amount"] == 12.0


# ===========================================================================
# Phase 12 — Calendar confirm
# ===========================================================================

PENDING_CALENDAR_ROW = {
    "id": INBOX_ID,
    "item_type": "calendar",
    "review_status": "pending",
    "title": "Dinner with Zoey",
    "body": "dinner with zoey next friday 7pm at jewel",
    "confidence": 0.93,
    "reviewed_at": None,
    "updated_at": "2024-01-01T12:00:00+00:00",
    "structured_json": {
        "title": "Dinner with Zoey",
        "proposed_datetime": "next Friday 7pm",
        "location": "Jewel",
        "notes": None,
    },
}

CONFIRMED_CALENDAR_ITEM = {
    **PENDING_CALENDAR_ROW,
    "review_status": "confirmed",
    "reviewed_at": "2024-01-01T12:05:00+00:00",
}

CALENDAR_INTENT_ROW = {
    "id": "calendar-intent-uuid-1",
    "inbox_item_id": INBOX_ID,
    "title": "Dinner with Zoey",
    "proposed_datetime": "next Friday 7pm",
    "location": "Jewel",
    "notes": None,
    "created_at": "2024-01-01T12:05:00+00:00",
}

CALENDAR_RPC_RESULT = {
    "inbox_item": CONFIRMED_CALENDAR_ITEM,
    "calendar_intent": CALENDAR_INTENT_ROW,
}


def _make_calendar_confirm_mock(
    inbox_results: list,
    calendar_intent_results: list | None = None,
    rpc_result=None,
    rpc_error: bool = False,
) -> MagicMock:
    """
    Routes .table('inbox_items') and .table('calendar_intents') to separate sub-mocks
    and stubs .rpc(...).execute(), mirroring _make_food_confirm_mock.
    """
    client_mock = MagicMock()

    inbox_tbl = MagicMock()
    inbox_tbl.select.return_value.eq.return_value.execute.side_effect = [
        MagicMock(data=d) for d in inbox_results
    ]

    calendar_tbl = MagicMock()
    calendar_tbl.select.return_value.eq.return_value.execute.side_effect = [
        MagicMock(data=d) for d in (calendar_intent_results or [])
    ]

    client_mock.table.side_effect = (
        lambda name: calendar_tbl if name == "calendar_intents" else inbox_tbl
    )

    if rpc_error:
        client_mock.rpc.return_value.execute.side_effect = Exception("rpc failed")
    else:
        client_mock.rpc.return_value.execute.return_value = MagicMock(data=rpc_result)

    return client_mock


# ---------------------------------------------------------------------------
# 1. Happy path
# ---------------------------------------------------------------------------


def test_confirm_pending_calendar_creates_intent_and_confirms(monkeypatch):
    mock = _make_calendar_confirm_mock(
        inbox_results=[[PENDING_CALENDAR_ROW]], rpc_result=CALENDAR_RPC_RESULT
    )
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.status_code == 200
    body = response.json()
    assert body["calendar_intent"]["id"] == "calendar-intent-uuid-1"
    assert body["inbox_item"]["review_status"] == "confirmed"


def test_confirm_calendar_reviewed_at_not_none(monkeypatch):
    mock = _make_calendar_confirm_mock(
        inbox_results=[[PENDING_CALENDAR_ROW]], rpc_result=CALENDAR_RPC_RESULT
    )
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.json()["inbox_item"]["reviewed_at"] is not None


def test_confirm_calendar_intent_inbox_item_id_matches(monkeypatch):
    mock = _make_calendar_confirm_mock(
        inbox_results=[[PENDING_CALENDAR_ROW]], rpc_result=CALENDAR_RPC_RESULT
    )
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.json()["calendar_intent"]["inbox_item_id"] == INBOX_ID


# ---------------------------------------------------------------------------
# 2. Idempotency
# ---------------------------------------------------------------------------


def test_confirm_calendar_already_confirmed_with_intent_returns_200(monkeypatch):
    """If already confirmed and a calendar_intent exists, return 200 without calling RPC."""
    mock = _make_calendar_confirm_mock(
        inbox_results=[[CONFIRMED_CALENDAR_ITEM]],
        calendar_intent_results=[[CALENDAR_INTENT_ROW]],
    )
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.status_code == 200
    mock.rpc.assert_not_called()


def test_confirm_calendar_already_confirmed_without_intent_returns_409(monkeypatch):
    """If confirmed but no calendar_intent, backfill is not supported → 409."""
    mock = _make_calendar_confirm_mock(
        inbox_results=[[CONFIRMED_CALENDAR_ITEM]],
        calendar_intent_results=[[]],
    )
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.status_code == 409


# ---------------------------------------------------------------------------
# 3. Recheck paths after RPC error
# ---------------------------------------------------------------------------


def test_confirm_calendar_rpc_error_then_confirmed_returns_200(monkeypatch):
    """RPC raises, re-read shows confirmed + intent already exists → 200 (concurrent win)."""
    mock = _make_calendar_confirm_mock(
        inbox_results=[[PENDING_CALENDAR_ROW], [CONFIRMED_CALENDAR_ITEM]],
        calendar_intent_results=[[CALENDAR_INTENT_ROW]],
        rpc_error=True,
    )
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.status_code == 200


def test_confirm_calendar_rpc_error_still_pending_returns_503(monkeypatch):
    """RPC raises, re-read shows still pending, same updated_at, no intent → 503."""
    mock = _make_calendar_confirm_mock(
        inbox_results=[[PENDING_CALENDAR_ROW], [PENDING_CALENDAR_ROW]],
        calendar_intent_results=[[]],
        rpc_error=True,
    )
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.status_code == 503
    assert "Calendar confirmation database operation failed" in response.json()["detail"]


def test_confirm_calendar_rpc_error_updated_at_changed_returns_409(monkeypatch):
    """RPC raises, re-read shows updated_at changed → concurrent modification → 409."""
    changed = {**PENDING_CALENDAR_ROW, "updated_at": "2024-01-01T13:30:00+00:00"}
    mock = _make_calendar_confirm_mock(
        inbox_results=[[PENDING_CALENDAR_ROW], [changed]],
        calendar_intent_results=[[]],
        rpc_error=True,
    )
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.status_code == 409


# ---------------------------------------------------------------------------
# 4. Validation
# ---------------------------------------------------------------------------


def test_confirm_calendar_missing_title_returns_400(monkeypatch):
    """structured_json without 'title' → 400, RPC not called."""
    bad = {**PENDING_CALENDAR_ROW, "structured_json": {"proposed_datetime": "Friday 7pm"}}
    mock = _make_calendar_confirm_mock(inbox_results=[[bad]])
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.status_code == 400
    mock.rpc.assert_not_called()


def test_confirm_calendar_whitespace_title_returns_400(monkeypatch):
    """Whitespace-only title → 400, RPC not called."""
    whitespace = {**PENDING_CALENDAR_ROW, "structured_json": {"title": "   "}}
    mock = _make_calendar_confirm_mock(inbox_results=[[whitespace]])
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.status_code == 400
    mock.rpc.assert_not_called()


# ---------------------------------------------------------------------------
# 5. Pipeline invariants
# ---------------------------------------------------------------------------


def test_confirm_calendar_does_not_python_insert(monkeypatch):
    """Python must not call .table('calendar_intents').insert() — only the RPC may write."""
    mock = _make_calendar_confirm_mock(
        inbox_results=[[PENDING_CALENDAR_ROW]], rpc_result=CALENDAR_RPC_RESULT
    )
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    calendar_tbl = mock.table("calendar_intents")
    calendar_tbl.insert.assert_not_called()


def test_confirm_calendar_rpc_function_name(monkeypatch):
    """The RPC must be called as 'confirm_calendar_item'."""
    mock = _make_calendar_confirm_mock(
        inbox_results=[[PENDING_CALENDAR_ROW]], rpc_result=CALENDAR_RPC_RESULT
    )
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert mock.rpc.call_args.args[0] == "confirm_calendar_item"


def test_confirm_calendar_needs_manual_classification_returns_409(monkeypatch):
    """Items with review_status='needs_manual_classification' cannot be confirmed → 409."""
    needs_manual = {**PENDING_CALENDAR_ROW, "review_status": "needs_manual_classification"}
    mock = _make_calendar_confirm_mock(inbox_results=[[needs_manual]])
    with patch("app.routes.review.get_supabase_client", return_value=mock):
        response = client.patch(f"/inbox/{INBOX_ID}/confirm", headers=_auth_header())
    assert response.status_code == 409
