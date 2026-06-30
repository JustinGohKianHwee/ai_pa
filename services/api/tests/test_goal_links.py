from copy import deepcopy
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.db.supabase_client import SupabaseConfigurationError
from app.main import app
from tests.conftest import mint_test_token

client = TestClient(app)
VALID_TOKEN = mint_test_token()

GOAL_ID = "11111111-1111-1111-1111-111111111111"
TASK_ID = "22222222-2222-2222-2222-222222222222"
LINK_ID = "33333333-3333-3333-3333-333333333333"
OWNER_ID = "00000000-0000-0000-0000-000000000001"

GOAL_ROW = {
    "id": GOAL_ID,
    "inbox_item_id": "44444444-4444-4444-4444-444444444444",
    "owner_id": OWNER_ID,
    "title": "Build the BTO fund",
    "description": None,
    "target": "100k",
    "target_date": "2027",
    "status": "active",
    "target_value": 100000,
    "target_currency": "SGD",
    "target_metric": "net_worth",
    "created_at": "2026-06-30T01:00:00+00:00",
    "updated_at": "2026-06-30T01:00:00+00:00",
}
TASK_ROW = {
    "id": TASK_ID,
    "owner_id": OWNER_ID,
    "title": "Book HDB appointment with a very long title that should be truncated after eighty characters exactly",
}
LINK_ROW = {
    "id": LINK_ID,
    "owner_id": OWNER_ID,
    "goal_id": GOAL_ID,
    "source_table": "tasks",
    "source_id": TASK_ID,
    "note": "Supports the housing goal",
    "created_at": "2026-06-30T02:00:00+00:00",
}


def _auth() -> dict:
    return {"Authorization": f"Bearer {VALID_TOKEN}"}


class FakeResult:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, db: "FakeSupabase", table: str):
        self.db = db
        self.table = table
        self.filters: list[tuple[str, object]] = []
        self.insert_payload: dict | None = None
        self.delete_mode = False

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, key, value):
        self.filters.append((key, value))
        return self

    def order(self, *_args, **_kwargs):
        return self

    def insert(self, payload):
        self.insert_payload = payload
        return self

    def delete(self):
        self.delete_mode = True
        return self

    def execute(self):
        self.db.exec_count += 1
        if self.db.fail_next_execute:
            self.db.fail_next_execute = False
            raise Exception("boom")

        if self.insert_payload is not None:
            self.db.insert_calls.append((self.table, self.insert_payload))
            if self.table == "goal_links":
                for row in self.db.tables["goal_links"]:
                    if (
                        row["goal_id"] == self.insert_payload["goal_id"]
                        and row["source_table"] == self.insert_payload["source_table"]
                        and row["source_id"] == self.insert_payload["source_id"]
                    ):
                        raise Exception("duplicate key value violates unique constraint")
                row = {
                    "id": "55555555-5555-5555-5555-555555555555",
                    "owner_id": OWNER_ID,
                    "created_at": "2026-06-30T03:00:00+00:00",
                    **self.insert_payload,
                }
                self.db.tables["goal_links"].append(row)
                return FakeResult([row])
            raise AssertionError(f"unexpected insert into {self.table}")

        rows = deepcopy(self.db.tables.get(self.table, []))
        for key, value in self.filters:
            rows = [row for row in rows if row.get(key) == value]

        if self.delete_mode:
            before = len(self.db.tables[self.table])
            self.db.tables[self.table] = [
                row
                for row in self.db.tables[self.table]
                if not all(row.get(key) == value for key, value in self.filters)
            ]
            return FakeResult([{"deleted": before - len(self.db.tables[self.table])}])

        return FakeResult(rows)


class FakeSupabase:
    def __init__(self, *, links=None, include_goal=True, include_task=True):
        self.tables = {
            "goals": [deepcopy(GOAL_ROW)] if include_goal else [],
            "tasks": [deepcopy(TASK_ROW)] if include_task else [],
            "goal_links": deepcopy(links or []),
        }
        self.insert_calls: list[tuple[str, dict]] = []
        self.exec_count = 0
        self.fail_next_execute = False

    def table(self, name):
        return FakeQuery(self, name)


def test_get_goal_returns_200():
    fake = FakeSupabase()
    with patch("app.routes.goals.get_supabase_client", return_value=fake):
        res = client.get(f"/goals/{GOAL_ID}", headers=_auth())
    assert res.status_code == 200
    assert res.json()["title"] == "Build the BTO fund"


def test_get_goal_missing_returns_404():
    fake = FakeSupabase(include_goal=False)
    with patch("app.routes.goals.get_supabase_client", return_value=fake):
        res = client.get(f"/goals/{GOAL_ID}", headers=_auth())
    assert res.status_code == 404


def test_post_link_success_returns_201_with_resolved_title_and_label():
    fake = FakeSupabase()
    with patch("app.routes.goals.get_supabase_client", return_value=fake):
        res = client.post(
            f"/goals/{GOAL_ID}/links",
            json={"source_table": "tasks", "source_id": TASK_ID, "note": "Supports the goal"},
            headers=_auth(),
        )
    assert res.status_code == 201
    body = res.json()
    assert body["label"] == "Task"
    assert body["title"] == TASK_ROW["title"][:80]
    assert body["note"] == "Supports the goal"


def test_post_duplicate_is_idempotent_200_returning_existing_link():
    fake = FakeSupabase(links=[LINK_ROW])
    with patch("app.routes.goals.get_supabase_client", return_value=fake):
        res = client.post(
            f"/goals/{GOAL_ID}/links",
            json={"source_table": "tasks", "source_id": TASK_ID, "note": "ignored"},
            headers=_auth(),
        )
    assert res.status_code == 200
    assert res.json()["id"] == LINK_ID
    assert fake.insert_calls == []


def test_post_unsupported_source_table_returns_422_and_does_not_insert():
    fake = FakeSupabase()
    with patch("app.routes.goals.get_supabase_client", return_value=fake):
        res = client.post(
            f"/goals/{GOAL_ID}/links",
            json={"source_table": "goals", "source_id": GOAL_ID},
            headers=_auth(),
        )
    assert res.status_code == 422
    assert fake.insert_calls == []


def test_post_missing_goal_returns_404():
    fake = FakeSupabase(include_goal=False)
    with patch("app.routes.goals.get_supabase_client", return_value=fake):
        res = client.post(
            f"/goals/{GOAL_ID}/links",
            json={"source_table": "tasks", "source_id": TASK_ID},
            headers=_auth(),
        )
    assert res.status_code == 404


def test_post_missing_source_record_returns_404():
    fake = FakeSupabase(include_task=False)
    with patch("app.routes.goals.get_supabase_client", return_value=fake):
        res = client.post(
            f"/goals/{GOAL_ID}/links",
            json={"source_table": "tasks", "source_id": TASK_ID},
            headers=_auth(),
        )
    assert res.status_code == 404
    assert res.json()["detail"] == "linked record not found"


def test_get_links_returns_resolved_titles_and_labels():
    fake = FakeSupabase(links=[LINK_ROW])
    with patch("app.routes.goals.get_supabase_client", return_value=fake):
        res = client.get(f"/goals/{GOAL_ID}/links", headers=_auth())
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 1
    assert body["items"][0]["label"] == "Task"
    assert body["items"][0]["title"] == TASK_ROW["title"][:80]


def test_get_links_goal_missing_returns_404():
    fake = FakeSupabase(include_goal=False)
    with patch("app.routes.goals.get_supabase_client", return_value=fake):
        res = client.get(f"/goals/{GOAL_ID}/links", headers=_auth())
    assert res.status_code == 404


def test_delete_existing_returns_204():
    fake = FakeSupabase(links=[LINK_ROW])
    with patch("app.routes.goals.get_supabase_client", return_value=fake):
        res = client.delete(f"/goals/{GOAL_ID}/links/{LINK_ID}", headers=_auth())
    assert res.status_code == 204
    assert fake.tables["goal_links"] == []


def test_delete_missing_returns_404():
    fake = FakeSupabase()
    with patch("app.routes.goals.get_supabase_client", return_value=fake):
        res = client.delete(f"/goals/{GOAL_ID}/links/{LINK_ID}", headers=_auth())
    assert res.status_code == 404


def test_auth_missing_token_returns_401():
    assert client.get(f"/goals/{GOAL_ID}/links").status_code == 401


def test_config_error_returns_500():
    with patch(
        "app.routes.goals.get_supabase_client",
        side_effect=SupabaseConfigurationError("missing"),
    ):
        res = client.get(f"/goals/{GOAL_ID}/links", headers=_auth())
    assert res.status_code == 500


def test_query_failure_returns_503():
    fake = FakeSupabase()
    fake.fail_next_execute = True
    with patch("app.routes.goals.get_supabase_client", return_value=fake):
        res = client.get(f"/goals/{GOAL_ID}/links", headers=_auth())
    assert res.status_code == 503
