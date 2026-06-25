"""
Phase 22d — statement import. Parser is unit-tested (pure); the import route is tested with a
mocked Supabase client verifying match-vs-import routing. Imported rows become pending finance
inbox_items (reviewed via the normal pipeline); matched rows link an existing money_event.
"""
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.db.supabase_client import SupabaseConfigurationError
from app.main import app
from app.services.statement_import import StatementParseError, parse_statement_csv

client = TestClient(app)

from tests.conftest import mint_test_token

VALID_TOKEN = mint_test_token()


def _auth() -> dict:
    return {"Authorization": f"Bearer {VALID_TOKEN}"}


# --- parser unit tests ---


def test_parse_basic_csv():
    csv = "date,description,amount,currency\n2026-06-01,Lunch,12.50,SGD\n2026-06-02,Gym,99,USD\n"
    rows = parse_statement_csv(csv, "SGD")
    assert len(rows) == 2
    assert rows[0] == {"occurred_on": "2026-06-01", "description": "Lunch", "amount": 12.5, "currency": "SGD"}
    assert rows[1]["currency"] == "USD"


def test_parse_uses_default_currency_when_no_column():
    rows = parse_statement_csv("date,description,amount\n2026-06-01,Lunch,10\n", "sgd")
    assert rows[0]["currency"] == "SGD"  # upper-cased default


def test_parse_skips_nonpositive_and_unparseable():
    csv = "description,amount\nRefund,-5\nBad,abc\nReal,8.00\n"
    rows = parse_statement_csv(csv, "SGD")
    assert len(rows) == 1 and rows[0]["amount"] == 8.0


def test_parse_strips_currency_symbols_and_commas():
    rows = parse_statement_csv("description,amount\nBig,\"$1,234.50\"\n", "SGD")
    assert rows[0]["amount"] == 1234.5


def test_parse_missing_amount_column_raises():
    with pytest.raises(StatementParseError):
        parse_statement_csv("date,description\n2026-06-01,Lunch\n", "SGD")


def test_parse_no_rows_raises():
    with pytest.raises(StatementParseError):
        parse_statement_csv("date,description,amount\n", "SGD")


# --- import route ---


def _import_mock(match_results: list) -> MagicMock:
    c = MagicMock()
    si = MagicMock()
    si.insert.return_value.execute.return_value = MagicMock(data=[{"id": "imp-1"}])
    si.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[{"id": "imp-1"}])
    me = MagicMock()
    me.select.return_value.eq.return_value.eq.return_value.eq.return_value.eq.return_value.limit.return_value.execute.side_effect = [
        MagicMock(data=d) for d in match_results
    ]
    cap = MagicMock()
    cap.insert.return_value.execute.return_value = MagicMock(data=[{"id": "cap-1"}])
    inb = MagicMock()
    inb.insert.return_value.execute.return_value = MagicMock(data=[{"id": "inb-1"}])
    sr = MagicMock()
    sr.insert.return_value.execute.return_value = MagicMock(data=[{"id": "row-1"}])
    c.table.side_effect = lambda n: {
        "statement_imports": si, "money_events": me,
        "capture_events": cap, "inbox_items": inb, "statement_rows": sr,
    }[n]
    return c


def _csv_file(text: str):
    return {"file": ("stmt.csv", text.encode("utf-8"), "text/csv")}


def test_import_auth_missing_401():
    res = client.post("/statements/import", files=_csv_file("description,amount\nX,1\n"))
    assert res.status_code == 401


def test_import_auth_non_owner_403():
    token = mint_test_token(sub="00000000-0000-0000-0000-0000000000ff")
    res = client.post(
        "/statements/import",
        files=_csv_file("description,amount\nX,1\n"),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 403


def test_import_routes_matched_vs_imported():
    csv = "date,description,amount,currency\n2026-06-01,Lunch,12.50,SGD\n2026-06-02,Gym,99,SGD\n"
    # row1 (12.50) matches an existing money_event; row2 (99) does not → imported
    mock = _import_mock(match_results=[[{"id": "me-1"}], []])
    with patch("app.routes.statements.get_supabase_client", return_value=mock):
        res = client.post("/statements/import", files=_csv_file(csv),
                          data={"default_currency": "SGD"}, headers=_auth())
    assert res.status_code == 200
    body = res.json()
    assert body["row_count"] == 2
    assert body["matched_count"] == 1
    assert body["imported_count"] == 1
    # the unmatched row created a capture_event + finance inbox_item
    mock.table("capture_events").insert.assert_called_once()
    mock.table("inbox_items").insert.assert_called_once()


def test_import_bad_csv_returns_422():
    mock = _import_mock(match_results=[])
    with patch("app.routes.statements.get_supabase_client", return_value=mock):
        res = client.post("/statements/import", files=_csv_file("date,description\nx,y\n"),
                          headers=_auth())
    assert res.status_code == 422  # no amount column


def test_list_imports_empty():
    mock = MagicMock()
    mock.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(data=[])
    with patch("app.routes.statements.get_supabase_client", return_value=mock):
        res = client.get("/statements", headers=_auth())
    assert res.status_code == 200
    assert res.json() == {"items": [], "total": 0}


def test_list_imports_db_config_500():
    with patch("app.routes.statements.get_supabase_client",
               side_effect=SupabaseConfigurationError("x")):
        assert client.get("/statements", headers=_auth()).status_code == 500
