"""
Phase 23a — notes & journal read routes. Lists are tested with a mocked Supabase client;
the ?q search applies an ILIKE filter. Confirm dispatch (RPC) is covered in test_review.py.
"""
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.db.supabase_client import SupabaseConfigurationError
from app.main import app
from tests.conftest import mint_test_token

client = TestClient(app)
VALID_TOKEN = mint_test_token()


def _auth() -> dict:
    return {"Authorization": f"Bearer {VALID_TOKEN}"}


NOTE_ROW = {
    "id": "note-1",
    "inbox_item_id": "inbox-1",
    "content": "call the plumber",
    "tags": ["home"],
    "created_at": "2024-01-01T12:00:00+00:00",
}
JOURNAL_ROW = {
    "id": "jrnl-1",
    "inbox_item_id": "inbox-2",
    "content": "felt good after the run",
    "mood": "energized",
    "created_at": "2024-01-01T12:00:00+00:00",
}


def _list_mock(rows: list) -> MagicMock:
    """Supports both the plain (.select.order) and search (.select.ilike.order) chains."""
    m = MagicMock()
    sel = m.table.return_value.select.return_value
    sel.order.return_value.execute.return_value = MagicMock(data=rows)
    sel.ilike.return_value.order.return_value.execute.return_value = MagicMock(data=rows)
    return m


# --- /notes ---


def test_list_notes_requires_auth():
    assert client.get("/notes").status_code == 401


def test_list_notes_returns_rows():
    mock = _list_mock([NOTE_ROW])
    with patch("app.routes.notes.get_supabase_client", return_value=mock):
        res = client.get("/notes", headers=_auth())
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 1
    assert body["items"][0]["content"] == "call the plumber"
    assert body["items"][0]["tags"] == ["home"]


def test_list_notes_search_applies_ilike():
    mock = _list_mock([NOTE_ROW])
    with patch("app.routes.notes.get_supabase_client", return_value=mock):
        res = client.get("/notes", params={"q": "plumber"}, headers=_auth())
    assert res.status_code == 200
    # the search term reached an ILIKE filter on content
    ilike = mock.table.return_value.select.return_value.ilike
    ilike.assert_called_once()
    assert ilike.call_args.args[0] == "content"
    assert "plumber" in ilike.call_args.args[1]


def test_list_notes_blank_query_skips_ilike():
    mock = _list_mock([NOTE_ROW])
    with patch("app.routes.notes.get_supabase_client", return_value=mock):
        res = client.get("/notes", params={"q": "   "}, headers=_auth())
    assert res.status_code == 200
    mock.table.return_value.select.return_value.ilike.assert_not_called()


def test_list_notes_db_config_500():
    with patch("app.routes.notes.get_supabase_client",
               side_effect=SupabaseConfigurationError("x")):
        assert client.get("/notes", headers=_auth()).status_code == 500


# --- /journal ---


def test_list_journal_requires_auth():
    assert client.get("/journal").status_code == 401


def test_list_journal_returns_rows():
    mock = _list_mock([JOURNAL_ROW])
    with patch("app.routes.journal.get_supabase_client", return_value=mock):
        res = client.get("/journal", headers=_auth())
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 1
    assert body["items"][0]["mood"] == "energized"


def test_list_journal_db_config_500():
    with patch("app.routes.journal.get_supabase_client",
               side_effect=SupabaseConfigurationError("x")):
        assert client.get("/journal", headers=_auth()).status_code == 500
