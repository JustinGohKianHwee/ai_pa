"""
Phase 22a — deterministic Financial Intelligence.

compute_summary is unit-tested directly (pure); the /financial_intelligence/summary route is
tested with a mocked Supabase client for wiring + metadata. Classifier schema tested too.
"""
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.db.supabase_client import SupabaseConfigurationError
from app.main import app
from app.services.classifier import FinancialSnapshotStructuredJson, GoalStructuredJson
from app.services.financial_intelligence import compute_monthly, compute_summary

client = TestClient(app)

from tests.conftest import mint_test_token

VALID_TOKEN = mint_test_token()


def _auth() -> dict:
    return {"Authorization": f"Bearer {VALID_TOKEN}"}


def _manual(**kw) -> dict:
    base = {
        "monthly_income_json": [],
        "monthly_investment_json": [],
        "liquid_cash_json": [],
        "liabilities_json": [],
    }
    base.update(kw)
    return base


SGD_PF = {
    "currency": "SGD",
    "market_value": 50000,
    "cash_value": 5000,
    "invested_value": 50000,
    "total_value": 55000,
    "market_value_complete": True,
    "market_value_missing": 0,
}


# --- compute_summary unit tests ---


def test_full_metrics_single_currency():
    manual = _manual(
        monthly_income_json=[{"currency": "SGD", "amount": 8000}],
        monthly_investment_json=[{"currency": "SGD", "amount": 2000}],
        liquid_cash_json=[{"currency": "SGD", "amount": 25000}],
        liabilities_json=[{"currency": "SGD", "amount": 12000}],
    )
    out = compute_summary(manual, [SGD_PF], {"SGD": 3000.0}, {"SGD": 3000.0})
    b = out["currencies"][0]
    assert b["currency"] == "SGD"
    assert b["liquid_cash"] == 25000.0
    assert b["invested"] == 50000.0
    assert b["broker_total"] == 55000.0
    assert b["liabilities"] == 12000.0
    # net worth = cash + broker_total - liabilities = 25000 + 55000 - 12000 (broker cash NOT double-counted)
    assert b["net_worth"]["value"] == 68000.0
    assert b["net_worth"]["complete"] is True
    assert b["net_worth"]["missing"] == []
    assert b["monthly_expenses_logged"] == 3000.0
    assert b["savings_rate"] == 0.625
    assert b["investment_rate"] == 0.25
    assert b["cash_runway_months"] == 8.3


def test_missing_manual_yields_unavailable():
    out = compute_summary(None, [SGD_PF], {"SGD": 3000.0}, {"SGD": 3000.0})
    b = out["currencies"][0]
    assert b["liquid_cash"] is None
    assert b["liabilities"] is None
    assert b["monthly_income"] is None
    assert b["savings_rate"] is None
    assert b["investment_rate"] is None
    assert b["cash_runway_months"] is None
    # portfolio still present; net worth uses only broker_total, flagged incomplete
    assert b["invested"] == 50000.0
    assert b["net_worth"]["value"] == 55000.0
    assert b["net_worth"]["complete"] is False
    assert set(b["net_worth"]["missing"]) == {"liquid_cash", "liabilities"}


def test_no_portfolio_snapshot_marks_invested_unavailable():
    manual = _manual(liquid_cash_json=[{"currency": "SGD", "amount": 10000}],
                     liabilities_json=[{"currency": "SGD", "amount": 4000}])
    out = compute_summary(manual, [], {}, {})
    b = out["currencies"][0]
    assert b["invested"] is None
    assert b["broker_total"] is None
    assert b["portfolio"] is None
    # net worth = cash - liabilities, missing broker_total
    assert b["net_worth"]["value"] == 6000.0
    assert b["net_worth"]["complete"] is False
    assert b["net_worth"]["missing"] == ["broker_total"]


def test_multi_currency_kept_separate_no_grand_total():
    manual = _manual(
        liquid_cash_json=[{"currency": "SGD", "amount": 25000}, {"currency": "USD", "amount": 1000}],
        monthly_income_json=[{"currency": "SGD", "amount": 8000}],
    )
    out = compute_summary(manual, [], {"SGD": 2000.0}, {"SGD": 2000.0})
    ccys = {b["currency"]: b for b in out["currencies"]}
    assert set(ccys) == {"SGD", "USD"}
    assert ccys["SGD"]["liquid_cash"] == 25000.0
    assert ccys["USD"]["liquid_cash"] == 1000.0
    # USD has no income → savings rate unavailable; no combined total anywhere
    assert ccys["USD"]["savings_rate"] is None
    assert "total" not in out and "grand_total" not in out


def test_savings_and_runway_unavailable_without_inputs():
    manual = _manual(liquid_cash_json=[{"currency": "SGD", "amount": 9000}])
    # no income → savings/investment None; no trailing expenses → runway None
    out = compute_summary(manual, [], {}, {})
    b = out["currencies"][0]
    assert b["savings_rate"] is None
    assert b["investment_rate"] is None
    assert b["cash_runway_months"] is None


# --- route tests ---


def _summary_mock(manual_data, snap_data, money_results):
    c = MagicMock()
    manual_tbl = MagicMock()
    manual_tbl.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=manual_data)
    snap_tbl = MagicMock()
    snap_tbl.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=snap_data)
    money_tbl = MagicMock()
    money_tbl.select.return_value.eq.return_value.eq.return_value.gte.return_value.lt.return_value.execute.side_effect = [
        MagicMock(data=d) for d in money_results
    ]
    c.table.side_effect = lambda name: {
        "manual_financial_snapshots": manual_tbl,
        "portfolio_snapshots": snap_tbl,
        "money_events": money_tbl,
    }[name]
    return c


def test_summary_auth_missing_401():
    assert client.get("/financial_intelligence/summary").status_code == 401


def test_summary_auth_non_owner_403():
    token = mint_test_token(sub="00000000-0000-0000-0000-0000000000ff")
    assert client.get(
        "/financial_intelligence/summary", headers={"Authorization": f"Bearer {token}"}
    ).status_code == 403


def test_summary_empty_all_unavailable():
    mock = _summary_mock([], [], [[], []])
    with patch("app.routes.financial_intelligence.get_supabase_client", return_value=mock):
        res = client.get("/financial_intelligence/summary", headers=_auth())
    assert res.status_code == 200
    body = res.json()
    assert body["has_manual_snapshot"] is False
    assert body["currencies"] == []
    assert body["portfolio_as_of"] is None


def test_summary_with_data():
    manual = _manual(
        as_of="today",
        monthly_income_json=[{"currency": "SGD", "amount": 8000}],
        liquid_cash_json=[{"currency": "SGD", "amount": 25000}],
        liabilities_json=[{"currency": "SGD", "amount": 12000}],
    )
    manual["created_at"] = "2026-06-24T00:00:00+00:00"
    snap = {"snapshot_date": "2026-06-23", "partial_failure": True,
            "portfolio_snapshot_currency_totals": [SGD_PF]}
    money = [[{"amount": 3000, "currency": "SGD"}], [{"amount": 9000, "currency": "SGD"}]]
    mock = _summary_mock([manual], [snap], money)
    with patch("app.routes.financial_intelligence.get_supabase_client", return_value=mock):
        res = client.get("/financial_intelligence/summary", headers=_auth())
    assert res.status_code == 200
    body = res.json()
    assert body["has_manual_snapshot"] is True
    assert body["portfolio_as_of"] == "2026-06-23"
    assert body["portfolio_partial"] is True
    sgd = body["currencies"][0]
    assert sgd["net_worth"]["value"] == 68000.0
    assert sgd["monthly_expenses_logged"] == 3000.0
    # trailing avg = 9000/3 = 3000 → runway 25000/3000 = 8.3
    assert sgd["cash_runway_months"] == 8.3


def test_summary_db_config_error_500():
    with patch(
        "app.routes.financial_intelligence.get_supabase_client",
        side_effect=SupabaseConfigurationError("missing key"),
    ):
        assert client.get("/financial_intelligence/summary", headers=_auth()).status_code == 500


# --- classifier schema ---


def test_financial_snapshot_schema_accepts_valid():
    m = FinancialSnapshotStructuredJson.model_validate(
        {"monthly_income": [{"currency": "sgd", "amount": 8000}], "as_of": "today"}
    )
    assert m.monthly_income[0].currency == "SGD"  # upper-cased


def test_financial_snapshot_schema_requires_at_least_one_entry():
    with pytest.raises(Exception):
        FinancialSnapshotStructuredJson.model_validate({"as_of": "today"})


def test_financial_snapshot_schema_rejects_negative_amount():
    with pytest.raises(Exception):
        FinancialSnapshotStructuredJson.model_validate(
            {"liquid_cash": [{"currency": "SGD", "amount": -5}]}
        )


def test_financial_snapshot_schema_rejects_extra_field():
    with pytest.raises(Exception):
        FinancialSnapshotStructuredJson.model_validate(
            {"liquid_cash": [{"currency": "SGD", "amount": 5}], "bogus": 1}
        )


# ===========================================================================
# Phase 22b-1 — compute_monthly unit tests
# ===========================================================================


def _msnap(**kw) -> dict:
    base = {"liquid_cash_json": [], "liabilities_json": [], "monthly_income_json": [], "as_of": "x"}
    base.update(kw)
    return base


def _psnap(date, partial, totals):
    return {"snapshot_date": date, "partial_failure": partial, "currency_totals": totals}


def test_monthly_expense_delta_and_savings():
    out = compute_monthly(
        "June 2026", "May 2026",
        current_expenses={"SGD": 1240.0},
        previous_expenses={"SGD": 1550.0},
        income={"SGD": 8000.0},
        manual_pair=None,
        portfolio_pair=None,
    )
    assert out["has_previous_month"] is True
    b = out["currencies"][0]
    assert b["logged_expenses"] == {"current": 1240.0, "previous": 1550.0, "delta": -310.0}
    # savings current = (8000-1240)/8000 = 0.845 ; previous = (8000-1550)/8000 ≈ 0.806
    assert b["savings_rate"]["current"] == 0.845
    assert b["savings_rate"]["previous"] is not None
    assert b["savings_rate"]["delta"] is not None
    assert any("Logged spending in June 2026" in s for s in b["explanation"])
    assert any("confirmed expense records only" in s for s in b["explanation"])


def test_monthly_previous_unavailable_for_new_user():
    out = compute_monthly(
        "June 2026", "May 2026",
        current_expenses={"SGD": 500.0},
        previous_expenses=None,
        income={"SGD": 8000.0},
        manual_pair=None,
        portfolio_pair=None,
    )
    assert out["has_previous_month"] is False
    b = out["currencies"][0]
    assert b["logged_expenses"]["previous"] is None
    assert b["logged_expenses"]["delta"] is None
    assert b["savings_rate"]["previous"] is None
    assert any("No prior month to compare" in s for s in b["explanation"])


def test_monthly_savings_unavailable_without_income():
    out = compute_monthly(
        "June 2026", "May 2026", {"SGD": 500.0}, {"SGD": 400.0}, {}, None, None
    )
    b = out["currencies"][0]
    assert b["savings_rate"]["current"] is None
    assert any("savings rate unavailable" in s.lower() for s in b["explanation"])


def test_monthly_manual_position_change_requires_two():
    pair = (
        _msnap(liquid_cash_json=[{"currency": "SGD", "amount": 26000}],
               liabilities_json=[{"currency": "SGD", "amount": 12000}], as_of="2026-06-01"),
        _msnap(liquid_cash_json=[{"currency": "SGD", "amount": 25000}],
               liabilities_json=[{"currency": "SGD", "amount": 12000}], as_of="2026-05-01"),
    )
    out = compute_monthly("June 2026", "May 2026", {"SGD": 0.0}, {"SGD": 0.0}, {}, pair, None)
    mc = out["currencies"][0]["manual_position_change"]
    # latest net = 26000-12000=14000 ; prev = 25000-12000=13000 ; delta = +1000
    assert mc["delta"] == 1000.0
    assert mc["from_as_of"] == "2026-05-01" and mc["to_as_of"] == "2026-06-01"


def test_monthly_portfolio_change_and_partial_label():
    pair = (
        _psnap("2026-06-23", True, [{"currency": "SGD", "total_value": 55000}]),
        _psnap("2026-05-23", False, [{"currency": "SGD", "total_value": 50000}]),
    )
    out = compute_monthly("June 2026", "May 2026", {}, {}, {}, None, pair)
    pc = out["currencies"][0]["portfolio_change"]
    assert pc["delta"] == 5000.0
    assert pc["partial"] is True
    assert any("Portfolio total for SGD" in s for s in out["currencies"][0]["explanation"])


def test_monthly_multi_currency_no_cross_sum():
    out = compute_monthly(
        "June 2026", "May 2026",
        current_expenses={"SGD": 1000.0, "USD": 200.0},
        previous_expenses={"SGD": 900.0, "USD": 100.0},
        income={"SGD": 8000.0},
        manual_pair=None,
        portfolio_pair=None,
    )
    ccys = {b["currency"]: b for b in out["currencies"]}
    assert set(ccys) == {"SGD", "USD"}
    assert ccys["USD"]["savings_rate"]["current"] is None  # no USD income
    assert "total" not in out and "grand_total" not in out


# --- /monthly route tests ---


def _monthly_mock(current_rows, history_rows, previous_rows, manual_rows, snap_rows):
    """money_events is queried 3x (current window, history-exists, previous window)."""
    c = MagicMock()
    money_tbl = MagicMock()
    money_tbl.select.return_value.eq.return_value.eq.return_value.gte.return_value.lt.return_value.execute.side_effect = [
        MagicMock(data=current_rows),
        MagicMock(data=previous_rows),
    ]
    money_tbl.select.return_value.eq.return_value.eq.return_value.lt.return_value.limit.return_value.execute.return_value = MagicMock(
        data=history_rows
    )
    manual_tbl = MagicMock()
    manual_tbl.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=manual_rows)
    snap_tbl = MagicMock()
    snap_tbl.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=snap_rows)
    c.table.side_effect = lambda name: {
        "money_events": money_tbl,
        "manual_financial_snapshots": manual_tbl,
        "portfolio_snapshots": snap_tbl,
    }[name]
    return c


def test_monthly_auth_missing_401():
    assert client.get("/financial_intelligence/monthly").status_code == 401


def test_monthly_auth_non_owner_403():
    token = mint_test_token(sub="00000000-0000-0000-0000-0000000000ff")
    assert client.get(
        "/financial_intelligence/monthly", headers={"Authorization": f"Bearer {token}"}
    ).status_code == 403


def test_monthly_route_with_history():
    cur = [{"amount": 1240, "currency": "SGD"}]
    prev = [{"amount": 1550, "currency": "SGD"}]
    manual = [_manual(monthly_income_json=[{"currency": "SGD", "amount": 8000}])]
    mock = _monthly_mock(cur, [{"id": "x"}], prev, manual, [])
    with patch("app.routes.financial_intelligence.get_supabase_client", return_value=mock):
        res = client.get("/financial_intelligence/monthly", headers=_auth())
    assert res.status_code == 200
    body = res.json()
    assert body["has_previous_month"] is True
    sgd = body["currencies"][0]
    assert sgd["logged_expenses"]["delta"] == -310.0


def test_monthly_route_new_user_previous_unavailable():
    cur = [{"amount": 500, "currency": "SGD"}]
    manual = [_manual(monthly_income_json=[{"currency": "SGD", "amount": 8000}])]
    mock = _monthly_mock(cur, [], None, manual, [])  # no history → previous not queried
    with patch("app.routes.financial_intelligence.get_supabase_client", return_value=mock):
        res = client.get("/financial_intelligence/monthly", headers=_auth())
    assert res.status_code == 200
    body = res.json()
    assert body["has_previous_month"] is False
    assert body["currencies"][0]["logged_expenses"]["previous"] is None


def test_monthly_db_config_error_500():
    with patch(
        "app.routes.financial_intelligence.get_supabase_client",
        side_effect=SupabaseConfigurationError("missing key"),
    ):
        assert client.get("/financial_intelligence/monthly", headers=_auth()).status_code == 500


# ===========================================================================
# Phase 22b-2 — financial goal progress
# ===========================================================================


def test_goal_schema_accepts_numeric_target():
    m = GoalStructuredJson.model_validate(
        {"title": "BTO fund", "target_value": 100000, "target_currency": "sgd",
         "target_metric": "liquid_cash"}
    )
    assert m.target_value == 100000
    assert m.target_currency == "SGD"  # upper-cased
    assert m.target_metric == "liquid_cash"


def test_goal_schema_rejects_negative_target():
    with pytest.raises(Exception):
        GoalStructuredJson.model_validate({"title": "x", "target_value": -1})


def test_goal_schema_rejects_bad_metric():
    with pytest.raises(Exception):
        GoalStructuredJson.model_validate(
            {"title": "x", "target_value": 100, "target_currency": "SGD", "target_metric": "bogus"}
        )


def _fin_goals_mock(manual_rows, snap_rows, money_results, goals_rows):
    c = MagicMock()
    manual_tbl = MagicMock()
    manual_tbl.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=manual_rows)
    snap_tbl = MagicMock()
    snap_tbl.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=snap_rows)
    money_tbl = MagicMock()
    money_tbl.select.return_value.eq.return_value.eq.return_value.gte.return_value.lt.return_value.execute.side_effect = [
        MagicMock(data=d) for d in money_results
    ]
    goals_tbl = MagicMock()
    gq = goals_tbl.select.return_value
    gq.eq.return_value = gq
    gq.not_ = gq
    gq.is_.return_value = gq
    gq.order.return_value = gq
    gq.execute.return_value = MagicMock(data=goals_rows)
    c.table.side_effect = lambda name: {
        "manual_financial_snapshots": manual_tbl,
        "portfolio_snapshots": snap_tbl,
        "money_events": money_tbl,
        "goals": goals_tbl,
    }[name]
    return c


def _fin_goal_row(**kw) -> dict:
    base = {
        "id": "goal-1", "title": "BTO fund", "status": "active",
        "target_value": 100000, "target_currency": "SGD", "target_metric": "net_worth",
    }
    base.update(kw)
    return base


def test_financial_goals_auth_missing_401():
    assert client.get("/financial_intelligence/financial-goals").status_code == 401


def test_financial_goals_auth_non_owner_403():
    token = mint_test_token(sub="00000000-0000-0000-0000-0000000000ff")
    assert client.get(
        "/financial_intelligence/financial-goals", headers={"Authorization": f"Bearer {token}"}
    ).status_code == 403


def test_financial_goals_empty():
    mock = _fin_goals_mock([], [], [[], []], [])
    with patch("app.routes.financial_intelligence.get_supabase_client", return_value=mock):
        res = client.get("/financial_intelligence/financial-goals", headers=_auth())
    assert res.status_code == 200
    assert res.json()["items"] == []


def test_financial_goals_progress_against_net_worth():
    manual = [_manual(liquid_cash_json=[{"currency": "SGD", "amount": 50000}])]
    mock = _fin_goals_mock(manual, [], [[], []], [_fin_goal_row()])
    with patch("app.routes.financial_intelligence.get_supabase_client", return_value=mock):
        res = client.get("/financial_intelligence/financial-goals", headers=_auth())
    item = res.json()["items"][0]
    assert item["base_value"] == 50000.0
    assert item["progress_pct"] == 0.5
    assert item["target_metric"] == "net_worth"


def test_financial_goals_progress_against_liquid_cash():
    manual = [_manual(liquid_cash_json=[{"currency": "SGD", "amount": 30000}],
                      liabilities_json=[{"currency": "SGD", "amount": 5000}])]
    goal = _fin_goal_row(target_metric="liquid_cash", target_value=60000)
    mock = _fin_goals_mock(manual, [], [[], []], [goal])
    with patch("app.routes.financial_intelligence.get_supabase_client", return_value=mock):
        res = client.get("/financial_intelligence/financial-goals", headers=_auth())
    item = res.json()["items"][0]
    assert item["base_value"] == 30000.0
    assert item["progress_pct"] == 0.5


def test_financial_goals_unavailable_when_currency_absent():
    manual = [_manual(liquid_cash_json=[{"currency": "SGD", "amount": 50000}])]
    goal = _fin_goal_row(target_currency="USD")
    mock = _fin_goals_mock(manual, [], [[], []], [goal])
    with patch("app.routes.financial_intelligence.get_supabase_client", return_value=mock):
        res = client.get("/financial_intelligence/financial-goals", headers=_auth())
    item = res.json()["items"][0]
    assert item["base_value"] is None
    assert item["progress_pct"] is None
