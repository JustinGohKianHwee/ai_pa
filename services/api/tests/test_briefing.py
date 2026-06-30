"""
Phase 24 — daily briefing & weekly reflection. The assemblers are pure and unit-tested; the routes
are tested with a mocked Supabase client and the DB-touching helpers patched (covered separately).
Everything is deterministic — no LLM — and currencies are never summed across currencies.
"""
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.db.supabase_client import SupabaseConfigurationError
from app.main import app
from app.services.briefing import build_daily_briefing, build_weekly_reflection
from tests.conftest import mint_test_token

client = TestClient(app)
VALID_TOKEN = mint_test_token()


def _auth() -> dict:
    return {"Authorization": f"Bearer {VALID_TOKEN}"}


# --- pure assembler: daily briefing ---


def test_daily_briefing_focus_orders_by_urgency_and_caps():
    tasks = [
        {"id": "1", "title": "someday thing", "urgency": "someday", "status": "open"},
        {"id": "2", "title": "today thing", "urgency": "today", "status": "open"},
        {"id": "3", "title": "this week", "urgency": "this_week", "status": "open"},
    ]
    b = build_daily_briefing("2026-06-27", tasks, [], {}, {}, {}, 0, True)
    assert [t["urgency"] for t in b["focus"]] == ["today", "this_week", "someday"]
    assert b["pending_inbox"] == 0


def test_daily_briefing_warnings_fire():
    tasks = [{"id": "1", "title": "x", "urgency": "today", "status": "open"}]
    b = build_daily_briefing(
        "2026-06-27", tasks, [], {}, {}, {"SGD": -50.0}, 12, has_income_snapshot=False
    )
    joined = " ".join(b["warnings"])
    assert "marked for today" in joined
    assert "awaiting review" in joined
    assert "Portfolio down 50.0 SGD" in joined
    assert "No income snapshot" in joined


def test_daily_briefing_empty_state():
    b = build_daily_briefing("2026-06-27", [], [], {}, {}, {}, 0, True)
    assert b["headline"] == "Nothing on today."
    assert b["warnings"] == []
    assert b["focus"] == []


def test_daily_briefing_spend_is_per_currency():
    b = build_daily_briefing("2026-06-27", [], [], {"SGD": 12.5, "USD": 3.0}, {"SGD": 200.0}, {}, 0, True)
    assert b["spend_today"] == [{"currency": "SGD", "amount": 12.5}, {"currency": "USD", "amount": 3.0}]
    assert b["spend_month_to_date"] == [{"currency": "SGD", "amount": 200.0}]


# --- pure assembler: weekly reflection ---


def test_weekly_reflection_trends_never_sum_currencies():
    r = build_weekly_reflection(
        "2026-06-21", "2026-06-27",
        confirmed_by_domain={"food": 5, "exercise": 2},
        spend_week_by_ccy={"SGD": 300.0, "USD": 40.0},
        prev_week_spend_by_ccy={"SGD": 250.0},
        exercise_count=2, food_count=5, active_goals=[],
        portfolio_delta_week_by_ccy={"SGD": -20.0},
    )
    # one trend line per currency, never a combined total
    assert any("SGD" in t and "▲ 50.0" in t for t in r["trends"])
    assert any("USD" in t for t in r["trends"])
    assert any("Portfolio down 20.0 SGD" in c for c in r["concerns"])
    assert any("Spending up 50.0 SGD" in c for c in r["concerns"])


def test_weekly_reflection_wins_and_progress():
    r = build_weekly_reflection(
        "2026-06-21", "2026-06-27", {"food": 3}, {}, {}, 0, 3,
        active_goals=[{"id": "g1", "title": "BTO fund", "target": "100k", "target_date": "2027"}],
        portfolio_delta_week_by_ccy={},
    )
    assert any("3 meals logged" in w for w in r["wins"])
    assert r["progress"][0]["title"] == "BTO fund"


# --- routes ---


def _briefing_mock(pending: int = 3, income: bool = True) -> MagicMock:
    c = MagicMock()
    tasks = MagicMock()
    tasks.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[{"id": "1", "title": "t", "urgency": "today", "due_date": None, "status": "open"}]
    )
    cal = MagicMock()
    cal.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
    inbox = MagicMock()
    inbox.select.return_value.in_.return_value.execute.return_value = MagicMock(count=pending, data=[])
    manual = MagicMock()
    manual.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
        data=[{"monthly_income_json": [{"currency": "SGD", "amount": 8000}]}] if income else []
    )
    ds = MagicMock()
    ds.upsert.return_value.execute.return_value = MagicMock(data=[{"id": "s-1"}])
    c.table.side_effect = lambda n: {
        "tasks": tasks, "calendar_intents": cal, "inbox_items": inbox,
        "manual_financial_snapshots": manual, "daily_summaries": ds,
    }[n]
    return c


def test_briefing_requires_auth():
    assert client.get("/briefing").status_code == 401


def test_briefing_returns_200_and_upserts(monkeypatch):
    monkeypatch.setenv("USER_TIMEZONE", "Asia/Singapore")
    mock = _briefing_mock()
    with patch("app.routes.briefing.get_supabase_client", return_value=mock), \
         patch("app.routes.briefing._expenses_by_currency", return_value={"SGD": 12.5}), \
         patch("app.routes.briefing._portfolio_delta", return_value={"SGD": -10.0}):
        res = client.get("/briefing", headers=_auth())
    assert res.status_code == 200
    body = res.json()
    assert body["briefing"]["kind"] == "daily"
    assert body["briefing"]["pending_inbox"] == 3
    mock.table("daily_summaries").upsert.assert_called_once()


def test_briefing_missing_timezone_503(monkeypatch):
    monkeypatch.delenv("USER_TIMEZONE", raising=False)
    res = client.get("/briefing", headers=_auth())
    assert res.status_code == 503


def test_briefing_db_config_500(monkeypatch):
    monkeypatch.setenv("USER_TIMEZONE", "Asia/Singapore")
    with patch("app.routes.briefing.get_supabase_client",
               side_effect=SupabaseConfigurationError("x")):
        assert client.get("/briefing", headers=_auth()).status_code == 500


def _reflection_mock() -> MagicMock:
    c = MagicMock()
    goals = MagicMock()
    goals.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[{"id": "g1", "title": "BTO", "target": "100k", "target_date": "2027"}]
    )
    ds = MagicMock()
    ds.upsert.return_value.execute.return_value = MagicMock(data=[{"id": "s-1"}])
    c.table.side_effect = lambda n: {"goals": goals, "daily_summaries": ds}[n]
    return c


def test_reflection_requires_auth():
    assert client.get("/reflection").status_code == 401


def test_reflection_returns_200_and_upserts(monkeypatch):
    monkeypatch.setenv("USER_TIMEZONE", "Asia/Singapore")
    mock = _reflection_mock()
    with patch("app.routes.briefing.get_supabase_client", return_value=mock), \
         patch("app.routes.briefing._confirmed_by_domain", return_value={"food": 3, "exercise": 1}), \
         patch("app.routes.briefing._expenses_by_currency", return_value={"SGD": 100.0}), \
         patch("app.routes.briefing._portfolio_delta", return_value={"SGD": 5.0}):
        res = client.get("/reflection", headers=_auth())
    assert res.status_code == 200
    body = res.json()
    assert body["reflection"]["kind"] == "weekly"
    assert body["reflection"]["progress"][0]["title"] == "BTO"
    mock.table("daily_summaries").upsert.assert_called_once()
