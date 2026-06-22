"""
Tests for GET /daily_review and GET /daily_review?date=today.

Phase 13 daily review — read-only. Three Supabase queries:
  Q1: capture_events.created_at in today's window (embedded inbox_items)
  Q2: inbox_items.reviewed_at in window + review_status='confirmed'
  Q3: inbox_items.reviewed_at in window + review_status='rejected'
pending_count computed in Python from Q1 results (no fourth query).

USER_TIMEZONE is required; missing or invalid → 503.
"""
from datetime import datetime as real_datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from app.db.supabase_client import SupabaseConfigurationError
from app.main import app

client = TestClient(app)

VALID_TOKEN = "test-dev-admin-token-xyz"


def _auth_header(token: str = VALID_TOKEN) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

CAPTURE_ROW_TASK = {
    "id": "cap-uuid-1",
    "created_at": "2026-06-22T04:00:00+00:00",
    "source": "telegram_text",
    "inbox_items": [
        {
            "id": "inbox-uuid-1",
            "item_type": "task",
            "review_status": "confirmed",
            "title": "Call mum",
            "created_at": "2026-06-22T04:00:01+00:00",
            "reviewed_at": "2026-06-22T05:00:00+00:00",
        }
    ],
}

CAPTURE_ROW_PENDING = {
    "id": "cap-uuid-2",
    "created_at": "2026-06-22T06:00:00+00:00",
    "source": "telegram_text",
    "inbox_items": [
        {
            "id": "inbox-uuid-2",
            "item_type": "food",
            "review_status": "pending",
            "title": "Chicken rice for lunch",
            "created_at": "2026-06-22T06:00:01+00:00",
            "reviewed_at": None,
        }
    ],
}

CAPTURE_ROW_NEEDS_MANUAL = {
    "id": "cap-uuid-3",
    "created_at": "2026-06-22T07:00:00+00:00",
    "source": "telegram_voice",
    "inbox_items": [
        {
            "id": "inbox-uuid-3",
            "item_type": "unknown",
            "review_status": "needs_manual_classification",
            "title": None,
            "created_at": "2026-06-22T07:00:01+00:00",
            "reviewed_at": None,
        }
    ],
}

CONFIRMED_TASK_ROW = {
    "id": "inbox-uuid-1",
    "item_type": "task",
    "review_status": "confirmed",
    "title": "Call mum",
    "created_at": "2026-06-22T04:00:01+00:00",
    "reviewed_at": "2026-06-22T05:00:00+00:00",
}

CONFIRMED_NOTE_ROW = {
    "id": "inbox-uuid-4",
    "item_type": "note",
    "review_status": "confirmed",
    "title": "Interesting article",
    "created_at": "2026-06-22T09:00:00+00:00",
    "reviewed_at": "2026-06-22T09:30:00+00:00",
}

CONFIRMED_JOURNAL_ROW = {
    "id": "inbox-uuid-5",
    "item_type": "journal",
    "review_status": "confirmed",
    "title": "Morning thoughts",
    "created_at": "2026-06-22T08:00:00+00:00",
    "reviewed_at": "2026-06-22T08:30:00+00:00",
}

CONFIRMED_UNKNOWN_ROW = {
    "id": "inbox-uuid-6",
    "item_type": "unknown",
    "review_status": "confirmed",
    "title": None,
    "created_at": "2026-06-22T10:00:00+00:00",
    "reviewed_at": "2026-06-22T10:30:00+00:00",
}

REJECTED_FINANCE_ROW = {
    "id": "inbox-uuid-7",
    "item_type": "finance",
    "review_status": "rejected",
    "title": "Old expense",
    "created_at": "2026-06-21T20:00:00+00:00",  # captured yesterday
    "reviewed_at": "2026-06-22T08:00:00+00:00",   # reviewed today
}

# PostgREST returns a one-to-one FK as a single dict (not a list) when the
# UNIQUE constraint on inbox_items.capture_event_id is known to the schema.
CAPTURE_ROW_TASK_DICT_SHAPE = {
    "id": "cap-uuid-1",
    "created_at": "2026-06-22T04:00:00+00:00",
    "source": "telegram_text",
    "inbox_items": {           # ← dict, not list
        "id": "inbox-uuid-1",
        "item_type": "task",
        "review_status": "confirmed",
        "title": "Call mum",
        "created_at": "2026-06-22T04:00:01+00:00",
        "reviewed_at": "2026-06-22T05:00:00+00:00",
    },
}

# Capture event with no linked inbox item (partial-failure recovery path).
CAPTURE_ROW_NO_INBOX = {
    "id": "cap-uuid-orphan",
    "created_at": "2026-06-22T03:00:00+00:00",
    "source": "telegram_text",
    "inbox_items": None,
}


def _make_daily_review_mock(
    captured_data: list,
    confirmed_data: list,
    rejected_data: list,
    db_error: bool = False,
) -> tuple[MagicMock, MagicMock, MagicMock]:
    """
    Returns (client_mock, cap_tbl, inbox_tbl).

    cap_tbl  — stubs Q1: capture_events.select.gte.lt.order.execute
    inbox_tbl — stubs Q2+Q3: inbox_items.select.gte.lt.eq.order.execute (side_effect list)

    Tests that need to inspect call args on cap_tbl use the second return value.
    """
    mock = MagicMock()
    cap_tbl = MagicMock()
    inbox_tbl = MagicMock()

    if db_error:
        (
            cap_tbl.select.return_value
            .gte.return_value
            .lt.return_value
            .order.return_value
            .execute
        ).side_effect = Exception("db error")
    else:
        (
            cap_tbl.select.return_value
            .gte.return_value
            .lt.return_value
            .order.return_value
            .execute.return_value
        ) = MagicMock(data=captured_data)

    (
        inbox_tbl.select.return_value
        .gte.return_value
        .lt.return_value
        .eq.return_value
        .order.return_value
        .execute
    ).side_effect = [
        MagicMock(data=confirmed_data),
        MagicMock(data=rejected_data),
    ]

    mock.table.side_effect = (
        lambda name: cap_tbl if name == "capture_events" else inbox_tbl
    )
    return mock, cap_tbl, inbox_tbl


# ---------------------------------------------------------------------------
# Auth guard
# ---------------------------------------------------------------------------


def test_daily_review_missing_token_returns_403(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("USER_TIMEZONE", "Asia/Singapore")
    response = client.get("/daily_review")
    assert response.status_code == 403


def test_daily_review_wrong_token_returns_403(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("USER_TIMEZONE", "Asia/Singapore")
    response = client.get("/daily_review", headers={"Authorization": "Bearer wrong"})
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Date parameter validation
# ---------------------------------------------------------------------------


def test_daily_review_date_yesterday_returns_422(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("USER_TIMEZONE", "Asia/Singapore")
    response = client.get("/daily_review?date=yesterday", headers=_auth_header())
    assert response.status_code == 422
    assert "today" in response.json()["detail"].lower()


def test_daily_review_date_iso_string_returns_422(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("USER_TIMEZONE", "Asia/Singapore")
    response = client.get("/daily_review?date=2026-06-22", headers=_auth_header())
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# USER_TIMEZONE — required, no silent default
# ---------------------------------------------------------------------------


def test_daily_review_missing_timezone_returns_503(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    monkeypatch.delenv("USER_TIMEZONE", raising=False)
    mock, _, _ = _make_daily_review_mock([], [], [])
    with patch("app.routes.daily_review.get_supabase_client", return_value=mock):
        response = client.get("/daily_review", headers=_auth_header())
    assert response.status_code == 503
    assert "USER_TIMEZONE" in response.json()["detail"]


def test_daily_review_invalid_timezone_returns_503(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("USER_TIMEZONE", "Not/ATimezone")
    mock, _, _ = _make_daily_review_mock([], [], [])
    with patch("app.routes.daily_review.get_supabase_client", return_value=mock):
        response = client.get("/daily_review", headers=_auth_header())
    assert response.status_code == 503
    assert "Not/ATimezone" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Empty day
# ---------------------------------------------------------------------------


def test_daily_review_empty_day_returns_zero_counts(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("USER_TIMEZONE", "Asia/Singapore")
    mock, _, _ = _make_daily_review_mock([], [], [])
    with patch("app.routes.daily_review.get_supabase_client", return_value=mock):
        response = client.get("/daily_review", headers=_auth_header())
    assert response.status_code == 200
    body = response.json()
    assert body["captured_count"] == 0
    assert body["confirmed_count"] == 0
    assert body["rejected_count"] == 0
    assert body["pending_count"] == 0
    assert body["captured_items"] == []
    assert body["confirmed_items"] == []
    assert body["rejected_items"] == []
    assert body["pending_items"] == []


def test_daily_review_empty_day_summary(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("USER_TIMEZONE", "Asia/Singapore")
    mock, _, _ = _make_daily_review_mock([], [], [])
    with patch("app.routes.daily_review.get_supabase_client", return_value=mock):
        response = client.get("/daily_review", headers=_auth_header())
    assert response.json()["summary"] == "Nothing captured or reviewed today."


# ---------------------------------------------------------------------------
# Response schema
# ---------------------------------------------------------------------------


def test_daily_review_response_has_required_fields(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("USER_TIMEZONE", "Asia/Singapore")
    mock, _, _ = _make_daily_review_mock([], [], [])
    with patch("app.routes.daily_review.get_supabase_client", return_value=mock):
        response = client.get("/daily_review", headers=_auth_header())
    body = response.json()
    for field in (
        "review_date", "timezone", "captured_count", "confirmed_count",
        "rejected_count", "pending_count", "confirmed_by_type",
        "captured_items", "confirmed_items", "rejected_items", "pending_items", "summary",
    ):
        assert field in body, f"missing field: {field}"


# ---------------------------------------------------------------------------
# Count accuracy
# ---------------------------------------------------------------------------


def test_daily_review_captured_count_from_capture_events(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("USER_TIMEZONE", "Asia/Singapore")
    mock, _, _ = _make_daily_review_mock(
        [CAPTURE_ROW_TASK, CAPTURE_ROW_PENDING], [], []
    )
    with patch("app.routes.daily_review.get_supabase_client", return_value=mock):
        response = client.get("/daily_review", headers=_auth_header())
    assert response.json()["captured_count"] == 2


def test_daily_review_confirmed_count_from_reviewed_at_window(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("USER_TIMEZONE", "Asia/Singapore")
    mock, _, _ = _make_daily_review_mock([], [CONFIRMED_TASK_ROW], [])
    with patch("app.routes.daily_review.get_supabase_client", return_value=mock):
        response = client.get("/daily_review", headers=_auth_header())
    assert response.json()["confirmed_count"] == 1


def test_daily_review_rejected_count_from_reviewed_at_window(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("USER_TIMEZONE", "Asia/Singapore")
    mock, _, _ = _make_daily_review_mock([], [], [REJECTED_FINANCE_ROW])
    with patch("app.routes.daily_review.get_supabase_client", return_value=mock):
        response = client.get("/daily_review", headers=_auth_header())
    assert response.json()["rejected_count"] == 1


def test_daily_review_pending_count_is_python_filter_no_extra_query(monkeypatch):
    """pending_count is derived from captured_items in Python — no fourth DB query."""
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("USER_TIMEZONE", "Asia/Singapore")
    mock, _, inbox_tbl = _make_daily_review_mock(
        [CAPTURE_ROW_TASK, CAPTURE_ROW_PENDING, CAPTURE_ROW_NEEDS_MANUAL], [], []
    )
    with patch("app.routes.daily_review.get_supabase_client", return_value=mock):
        response = client.get("/daily_review", headers=_auth_header())
    body = response.json()
    # CAPTURE_ROW_PENDING (pending) + CAPTURE_ROW_NEEDS_MANUAL (needs_manual_classification)
    assert body["pending_count"] == 2
    # Q2+Q3 called exactly twice (confirmed + rejected) — no additional inbox query
    assert inbox_tbl.select.return_value.gte.return_value.lt.return_value.eq.return_value \
        .order.return_value.execute.call_count == 2


# ---------------------------------------------------------------------------
# Timezone boundary
# ---------------------------------------------------------------------------


def test_daily_review_timezone_boundary_uses_sgt_midnight_utc(monkeypatch):
    """USER_TIMEZONE=Asia/Singapore: Q1 gte/lt args use SGT midnight → UTC."""
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("USER_TIMEZONE", "Asia/Singapore")

    # Fixed "now" = 2026-06-22 14:30:00 SGT (UTC+8).
    # SGT midnight 2026-06-22 → UTC: 2026-06-21T16:00:00+00:00
    # SGT midnight 2026-06-23 → UTC: 2026-06-22T16:00:00+00:00
    fixed_now = real_datetime(2026, 6, 22, 14, 30, 0, tzinfo=ZoneInfo("Asia/Singapore"))

    mock, cap_tbl, _ = _make_daily_review_mock([], [], [])
    with (
        patch("app.routes.daily_review.get_supabase_client", return_value=mock),
        patch("app.routes.daily_review.datetime") as mock_dt,
    ):
        mock_dt.now.return_value = fixed_now
        mock_dt.combine.side_effect = real_datetime.combine
        response = client.get("/daily_review", headers=_auth_header())

    assert response.status_code == 200
    gte_args = cap_tbl.select.return_value.gte.call_args[0]
    lt_args = cap_tbl.select.return_value.gte.return_value.lt.call_args[0]
    assert gte_args[0] == "created_at"
    assert lt_args[0] == "created_at"
    assert "2026-06-21T16:00:00" in gte_args[1]
    assert "2026-06-22T16:00:00" in lt_args[1]


# ---------------------------------------------------------------------------
# confirmed_by_type grouping
# ---------------------------------------------------------------------------


def test_daily_review_confirmed_by_type_task(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("USER_TIMEZONE", "Asia/Singapore")
    mock, _, _ = _make_daily_review_mock([], [CONFIRMED_TASK_ROW], [])
    with patch("app.routes.daily_review.get_supabase_client", return_value=mock):
        response = client.get("/daily_review", headers=_auth_header())
    assert response.json()["confirmed_by_type"]["task"] == 1
    assert response.json()["confirmed_by_type"]["other"] == 0


def test_daily_review_confirmed_by_type_unknown_goes_to_other(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("USER_TIMEZONE", "Asia/Singapore")
    mock, _, _ = _make_daily_review_mock([], [CONFIRMED_UNKNOWN_ROW], [])
    with patch("app.routes.daily_review.get_supabase_client", return_value=mock):
        response = client.get("/daily_review", headers=_auth_header())
    by_type = response.json()["confirmed_by_type"]
    assert by_type["other"] == 1
    assert by_type["task"] == 0


def test_daily_review_note_and_journal_in_confirmed_by_type(monkeypatch):
    """note/journal types appear in confirmed_by_type without implying a domain record."""
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("USER_TIMEZONE", "Asia/Singapore")
    mock, _, _ = _make_daily_review_mock(
        [], [CONFIRMED_NOTE_ROW, CONFIRMED_JOURNAL_ROW], []
    )
    with patch("app.routes.daily_review.get_supabase_client", return_value=mock):
        response = client.get("/daily_review", headers=_auth_header())
    by_type = response.json()["confirmed_by_type"]
    assert by_type["note"] == 1
    assert by_type["journal"] == 1


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def test_daily_review_summary_includes_type_breakdown_when_confirmed(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("USER_TIMEZONE", "Asia/Singapore")
    mock, _, _ = _make_daily_review_mock(
        [CAPTURE_ROW_TASK], [CONFIRMED_TASK_ROW], []
    )
    with patch("app.routes.daily_review.get_supabase_client", return_value=mock):
        response = client.get("/daily_review", headers=_auth_header())
    summary = response.json()["summary"]
    assert "confirmed" in summary
    assert "task" in summary


def test_daily_review_rejected_only_day_not_empty_summary(monkeypatch):
    """A day with only rejections must NOT return 'Nothing captured or reviewed today.'"""
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("USER_TIMEZONE", "Asia/Singapore")
    # captured=0, confirmed=0, rejected=1
    mock, _, _ = _make_daily_review_mock([], [], [REJECTED_FINANCE_ROW])
    with patch("app.routes.daily_review.get_supabase_client", return_value=mock):
        response = client.get("/daily_review", headers=_auth_header())
    summary = response.json()["summary"]
    assert summary != "Nothing captured or reviewed today."
    assert "rejected" in summary


# ---------------------------------------------------------------------------
# Read-only invariant
# ---------------------------------------------------------------------------


def test_daily_review_makes_no_db_writes(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("USER_TIMEZONE", "Asia/Singapore")
    mock, cap_tbl, inbox_tbl = _make_daily_review_mock([], [], [])
    with patch("app.routes.daily_review.get_supabase_client", return_value=mock):
        client.get("/daily_review", headers=_auth_header())
    cap_tbl.insert.assert_not_called()
    cap_tbl.update.assert_not_called()
    cap_tbl.delete.assert_not_called()
    inbox_tbl.insert.assert_not_called()
    inbox_tbl.update.assert_not_called()
    inbox_tbl.delete.assert_not_called()


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_daily_review_db_config_error_returns_500(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("USER_TIMEZONE", "Asia/Singapore")
    with patch(
        "app.routes.daily_review.get_supabase_client",
        side_effect=SupabaseConfigurationError("missing key"),
    ):
        response = client.get("/daily_review", headers=_auth_header())
    assert response.status_code == 500


def test_daily_review_db_query_failure_returns_503(monkeypatch):
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("USER_TIMEZONE", "Asia/Singapore")
    mock, _, _ = _make_daily_review_mock([], [], [], db_error=True)
    with patch("app.routes.daily_review.get_supabase_client", return_value=mock):
        response = client.get("/daily_review", headers=_auth_header())
    assert response.status_code == 503


# ---------------------------------------------------------------------------
# PostgREST shape handling and timestamp correctness
# ---------------------------------------------------------------------------


def test_daily_review_handles_dict_inbox_items_shape(monkeypatch):
    """PostgREST may return a one-to-one FK as a single dict — must not crash."""
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("USER_TIMEZONE", "Asia/Singapore")
    mock, _, _ = _make_daily_review_mock([CAPTURE_ROW_TASK_DICT_SHAPE], [], [])
    with patch("app.routes.daily_review.get_supabase_client", return_value=mock):
        response = client.get("/daily_review", headers=_auth_header())
    assert response.status_code == 200
    body = response.json()
    assert body["captured_count"] == 1
    assert len(body["captured_items"]) == 1
    assert body["captured_items"][0]["id"] == "inbox-uuid-1"
    assert body["captured_items"][0]["item_type"] == "task"


def test_daily_review_captured_items_use_capture_event_timestamp(monkeypatch):
    """captured_items[].created_at must be the outer capture_event timestamp."""
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("USER_TIMEZONE", "Asia/Singapore")
    mock, _, _ = _make_daily_review_mock([CAPTURE_ROW_TASK], [], [])
    with patch("app.routes.daily_review.get_supabase_client", return_value=mock):
        response = client.get("/daily_review", headers=_auth_header())
    body = response.json()
    assert len(body["captured_items"]) == 1
    # Capture event created_at (04:00:00), not inbox_item created_at (04:00:01).
    assert body["captured_items"][0]["created_at"] == CAPTURE_ROW_TASK["created_at"]


def test_daily_review_orphaned_capture_in_count_and_list(monkeypatch):
    """A capture with no linked inbox item must appear in captured_count and captured_items."""
    monkeypatch.setenv("DEV_ADMIN_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("USER_TIMEZONE", "Asia/Singapore")
    mock, _, _ = _make_daily_review_mock([CAPTURE_ROW_NO_INBOX], [], [])
    with patch("app.routes.daily_review.get_supabase_client", return_value=mock):
        response = client.get("/daily_review", headers=_auth_header())
    body = response.json()
    assert body["captured_count"] == 1
    assert len(body["captured_items"]) == 1
    item = body["captured_items"][0]
    assert item["id"] == "cap-uuid-orphan"
    assert item["review_status"] == "orphaned"
    assert item["created_at"] == CAPTURE_ROW_NO_INBOX["created_at"]
    # Orphaned captures are not pending review.
    assert body["pending_count"] == 0
