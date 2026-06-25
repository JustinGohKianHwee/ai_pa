"""
Phase 22d / 22d-2 — statement import. CSV parser is unit-tested (pure); PDF text extraction +
LLM row structuring are unit-tested with pypdf / OpenAI mocked. The import route is tested with a
mocked Supabase client verifying match-vs-import routing for both CSV and PDF uploads. Imported
rows become pending finance inbox_items (reviewed via the normal pipeline); matched rows link an
existing money_event.
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.db.supabase_client import SupabaseConfigurationError
from app.main import app
from app.services.statement_import import StatementParseError, parse_statement_csv
from app.services.statement_pdf import (
    StatementExtractionError,
    extract_pdf_text,
    extract_rows_from_text,
)

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
    assert rows[0] == {
        "occurred_on": "2026-06-01", "raw_descriptor": "Lunch", "merchant": "Lunch",
        "amount": 12.5, "currency": "SGD", "category": None,
    }
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


def test_parse_reads_category_column_snapped_to_taxonomy():
    csv = "description,amount,category\nLunch,12.50,food & drink\nMystery,5,Wat\n"
    rows = parse_statement_csv(csv, "SGD")
    assert rows[0]["category"] == "Food & Drink"  # canonical
    assert rows[1]["category"] is None  # unrecognised → uncategorized


def test_parse_no_category_column_is_none():
    rows = parse_statement_csv("description,amount\nLunch,12.50\n", "SGD")
    assert rows[0]["category"] is None


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


# --- PDF extraction (Phase 22d-2) ---


def _fake_pdf_reader(page_texts: list):
    reader = MagicMock()
    reader.pages = [MagicMock(extract_text=MagicMock(return_value=t)) for t in page_texts]
    return reader


def test_extract_pdf_text_concatenates_pages():
    with patch("pypdf.PdfReader", return_value=_fake_pdf_reader(["page one", "page two"])):
        text = extract_pdf_text(b"%PDF-1.4 ...")
    assert "page one" in text and "page two" in text


def test_extract_pdf_text_no_text_layer_raises():
    # A scanned image yields empty extract_text() on every page → clear error, not silent import.
    with patch("pypdf.PdfReader", return_value=_fake_pdf_reader(["", "   "])):
        with pytest.raises(StatementParseError):
            extract_pdf_text(b"%PDF-1.4 ...")


def test_extract_pdf_text_unreadable_raises():
    with patch("pypdf.PdfReader", side_effect=ValueError("bad pdf")):
        with pytest.raises(StatementParseError):
            extract_pdf_text(b"not really a pdf")


def _openai_mock(content: str) -> MagicMock:
    c = MagicMock()
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    c.chat.completions.create = AsyncMock(return_value=resp)
    return c


@pytest.mark.asyncio
async def test_extract_rows_from_text_structures_expenses(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    payload = json.dumps({
        "rows": [
            {"occurred_on": "2026-06-01", "raw_descriptor": "STARBUCKS SG", "merchant": "Starbucks",
             "amount": 12.5, "currency": "SGD", "category": "food & drink"},
            {"occurred_on": "2026-06-02", "raw_descriptor": "GYM XYZ", "merchant": None,
             "amount": 99, "currency": "", "category": "Nonsense Category"},
        ]
    })
    with patch("app.services.statement_pdf.AsyncOpenAI", return_value=_openai_mock(payload)):
        rows = await extract_rows_from_text("raw statement text", "usd")
    assert len(rows) == 2
    # raw_descriptor preserved verbatim; merchant normalized; category snapped to taxonomy
    assert rows[0] == {
        "occurred_on": "2026-06-01", "raw_descriptor": "STARBUCKS SG", "merchant": "Starbucks",
        "amount": 12.5, "currency": "SGD", "category": "Food & Drink",
    }
    # blank currency falls back to the upper-cased default; unknown category → None; merchant None
    assert rows[1]["currency"] == "USD"
    assert rows[1]["category"] is None
    assert rows[1]["merchant"] is None


@pytest.mark.asyncio
async def test_extract_rows_grab_is_merchant_only_category_unknown(monkeypatch):
    """Ambiguous Grab rows: descriptor preserved verbatim, merchant 'Grab', category left null."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    descriptor = "GRAB* GPC-A-9A8QF2CWW4 SI SGP 06MAY"
    payload = json.dumps({
        "rows": [
            {"occurred_on": "06MAY", "raw_descriptor": descriptor, "merchant": "Grab",
             "amount": 18.4, "currency": "SGD", "category": None},
        ]
    })
    with patch("app.services.statement_pdf.AsyncOpenAI", return_value=_openai_mock(payload)):
        rows = await extract_rows_from_text("text", "SGD")
    assert rows[0]["raw_descriptor"] == descriptor  # GPC code preserved exactly
    assert rows[0]["merchant"] == "Grab"
    assert rows[0]["category"] is None  # transport vs food is ambiguous → user decides


@pytest.mark.asyncio
async def test_extract_rows_skips_nonpositive_amount(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    # The row validator rejects amount<=0; an invalid row fails the whole extraction (caught row-level
    # would hide model errors), so a negative amount surfaces as an extraction error.
    payload = json.dumps({"rows": [{"raw_descriptor": "Refund", "amount": -5, "currency": "SGD"}]})
    with patch("app.services.statement_pdf.AsyncOpenAI", return_value=_openai_mock(payload)):
        with pytest.raises(StatementExtractionError):
            await extract_rows_from_text("text", "SGD")


@pytest.mark.asyncio
async def test_extract_rows_no_api_key_raises(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(StatementExtractionError):
        await extract_rows_from_text("text", "SGD")


@pytest.mark.asyncio
async def test_extract_rows_bad_json_raises(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    with patch("app.services.statement_pdf.AsyncOpenAI", return_value=_openai_mock("not json")):
        with pytest.raises(StatementExtractionError):
            await extract_rows_from_text("text", "SGD")


# --- PDF import route (Phase 22d-2) ---


def _pdf_file(data: bytes = b"%PDF-1.4 fake"):
    return {"file": ("stmt.pdf", data, "application/pdf")}


def test_import_pdf_routes_matched_vs_imported():
    # Two extracted rows: 12.50 matches an existing money_event, 99 does not → imported.
    grab = "GRAB* GPC-A-9C2JH7NGXD SI SGP 20MAY"
    extracted = [
        {"occurred_on": "2026-06-01", "raw_descriptor": "STARBUCKS SG", "merchant": "Starbucks",
         "amount": 12.5, "currency": "SGD", "category": "Food & Drink"},
        # ambiguous Grab row: merchant set, category null → imported for review
        {"occurred_on": "2026-05-20", "raw_descriptor": grab, "merchant": "Grab",
         "amount": 99.0, "currency": "SGD", "category": None},
    ]
    mock = _import_mock(match_results=[[{"id": "me-1"}], []])
    with patch("app.routes.statements.get_supabase_client", return_value=mock), \
         patch("app.routes.statements.extract_pdf_text", return_value="text"), \
         patch("app.routes.statements.extract_rows_from_text",
               new=AsyncMock(return_value=extracted)):
        res = client.post("/statements/import", files=_pdf_file(),
                          data={"default_currency": "SGD"}, headers=_auth())
    assert res.status_code == 200
    body = res.json()
    assert body["row_count"] == 2
    assert body["matched_count"] == 1
    assert body["imported_count"] == 1
    mock.table("capture_events").insert.assert_called_once()
    # the imported Grab row: merchant 'Grab', category null (needs review), raw descriptor preserved
    inbox_payload = mock.table("inbox_items").insert.call_args[0][0]
    assert inbox_payload["structured_json"]["merchant"] == "Grab"
    assert inbox_payload["structured_json"]["category"] is None
    assert inbox_payload["structured_json"]["notes"] == grab
    # statement_rows.description stores the verbatim descriptor too
    sr_payload = mock.table("statement_rows").insert.call_args[0][0]
    assert sr_payload["description"] == grab


def test_import_pdf_no_text_layer_422():
    mock = _import_mock(match_results=[])
    with patch("app.routes.statements.get_supabase_client", return_value=mock), \
         patch("app.routes.statements.extract_pdf_text",
               side_effect=StatementParseError("scanned image")):
        res = client.post("/statements/import", files=_pdf_file(), headers=_auth())
    assert res.status_code == 422


def test_import_pdf_extraction_unavailable_503():
    mock = _import_mock(match_results=[])
    with patch("app.routes.statements.get_supabase_client", return_value=mock), \
         patch("app.routes.statements.extract_pdf_text", return_value="text"), \
         patch("app.routes.statements.extract_rows_from_text",
               new=AsyncMock(side_effect=StatementExtractionError("no key"))):
        res = client.post("/statements/import", files=_pdf_file(), headers=_auth())
    assert res.status_code == 503


def test_import_pdf_no_rows_found_422():
    mock = _import_mock(match_results=[])
    with patch("app.routes.statements.get_supabase_client", return_value=mock), \
         patch("app.routes.statements.extract_pdf_text", return_value="text"), \
         patch("app.routes.statements.extract_rows_from_text", new=AsyncMock(return_value=[])):
        res = client.post("/statements/import", files=_pdf_file(), headers=_auth())
    assert res.status_code == 422
