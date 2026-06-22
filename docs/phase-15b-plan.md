# Phase 15b — Memory-ready foundation (plan for Codex execution)

> **Workflow:** Claude Code authored this plan; **Codex executes it**. Do not make
> architectural decisions — if anything is ambiguous, stop and ask. Recommended Codex
> settings: **model 5.5, effort high** (edits the verified confirm RPCs — pipeline-sensitive).

---

## Context & principle
Phases 1–14.5 + 15a are on `main`. Before deployment (16) we add the **cheap, retrofit-painful
schema contracts** that the future memory/vector layer needs — and nothing more. **No vector
DB, no embeddings, no `embedding_queue`, no `daily_summaries` (deferred to the summaries
phase), no LLM.** This phase is almost entirely SQL migrations.

Two pieces:
1. **`owner_id` everywhere** — a common ownership column on all existing tables (single-user
   today, multi-user-ready tomorrow). Cheap now, painful to backfill after data grows.
2. **`memory_events`** — an append-only event log, **populated atomically** at each
   confirmation and on snapshot creation, so a real memory backlog accrues from day one (the
   future vector phase embeds these).

### Confirmed decisions (do not revisit)
- `memory_events` is **populated now, atomically inside the confirm/snapshot RPCs**.
- `daily_summaries` is **deferred** (added with its generator in the summaries phase).
- Single-user: `owner_id` defaults to the owner's UUID; no per-user RLS policies (the existing
  service-role + owner-gate model stands).

---

## Part A — Migration `0010_owner_id.sql`

Add `owner_id` to every existing table that lacks it: `capture_events`, `inbox_items`,
`agent_runs`, `tasks`, `money_events`, `food_logs`, `calendar_intents`. (The
`portfolio_snapshot*` tables already have `owner_id`.)

For each table, the pattern:
```sql
alter table <t> add column if not exists owner_id text;
update <t> set owner_id = '<OWNER_USER_ID>' where owner_id is null;
alter table <t> alter column owner_id set default '<OWNER_USER_ID>';
alter table <t> alter column owner_id set not null;
```
- **`<OWNER_USER_ID>` placeholder:** the user replaces it with their real Supabase owner UUID
  before applying (migrations are applied manually). Put a clear comment at the top:
  `-- Replace <OWNER_USER_ID> with your Supabase owner UUID before running.`
- The `default` means existing inserts (Telegram capture, classification, etc.) auto-fill
  `owner_id` with **no application code change**.
- RLS is unchanged (already enabled/locked in 0008); adding a column doesn't affect it.

> Codex: do not change any application insert/read code for `owner_id` — the column default
> handles single-user. Do not apply the migration.

---

## Part B — Migration `0011_memory_events.sql`

### B1. Table
```sql
create table if not exists memory_events (
    id uuid primary key default gen_random_uuid(),
    owner_id text not null default '<OWNER_USER_ID>',
    occurred_at timestamptz not null default now(),
    domain text not null,           -- 'task' | 'money' | 'food' | 'calendar' | 'portfolio_snapshot'
    event_type text not null,       -- 'confirmed' | 'snapshot_created'
    payload_json jsonb not null default '{}'::jsonb,  -- compact, retrieval-friendly summary (NOT the full row)
    source_table text not null,     -- 'tasks' | 'money_events' | 'food_logs' | 'calendar_intents' | 'portfolio_snapshots'
    source_id uuid,                 -- the domain record id
    created_at timestamptz not null default now()
);
create index if not exists idx_memory_events_owner_occurred on memory_events (owner_id, occurred_at desc);
create index if not exists idx_memory_events_source on memory_events (source_table, source_id);

alter table memory_events enable row level security;
alter table memory_events force row level security;
revoke all on table memory_events from anon, authenticated;
```
Append-only by convention (no app updates/deletes). Same `<OWNER_USER_ID>` placeholder note.

### B2. Populate from the confirm RPCs (atomic)
`CREATE OR REPLACE` each of `confirm_task_item`, `confirm_finance_item`, `confirm_food_item`,
`confirm_calendar_item` (signatures unchanged: `(uuid, timestamptz)`), **preserving their exact
existing logic** (inspect 0002/0003/0006/0007), and add — as the last step before `return`,
inside the same transaction — an insert into `memory_events`:
```sql
insert into memory_events (domain, event_type, payload_json, source_table, source_id, occurred_at)
values (
  '<domain>', 'confirmed',
  jsonb_build_object(...compact fields...),
  '<source_table>', v_new_domain_row_id, now()
);
```
- `owner_id` is filled by the column default (single-user) — do not hardcode it in the insert.
- `source_id` = the id of the domain row the RPC just created.
- `payload_json` = a **concise** summary, not the whole row. Inspect each domain table for the
  right fields:
  - task → `{title, status, due_date}` (whatever the tasks table actually has)
  - money → `{amount, currency, description, direction}`
  - food → `{description, calories, protein_g}` (use real column names)
  - calendar → `{title, start_at, end_at}`
- **Atomicity is the point:** because the insert is inside the existing single-statement
  PL/pgSQL transaction, if confirmation raises (idempotency guard, missing inbox item, etc.)
  the memory_event is rolled back too. Never write a memory_event for a confirmation that
  didn't happen.

### B3. Populate on snapshot creation (idempotent)
`CREATE OR REPLACE create_portfolio_snapshot(...)` (from 0009; signature unchanged), preserving
its logic, and after the header upsert + child re-insert, **upsert one** `snapshot_created`
event keyed by `source_id`:
```sql
delete from memory_events where source_table = 'portfolio_snapshots' and source_id = v_snapshot_id;
insert into memory_events (domain, event_type, payload_json, source_table, source_id, occurred_at)
values ('portfolio_snapshot', 'snapshot_created',
        jsonb_build_object('snapshot_date', p_snapshot_date, 'partial_failure', p_partial_failure,
                           'currency_totals', p_currency_totals),
        'portfolio_snapshots', v_snapshot_id, p_generated_at);
```
This keeps **one** snapshot event per day (matching the snapshot's replace-per-day semantics).

---

## Part C — Application code
**None required.** `owner_id` is default-filled; population lives in the RPCs the app already
calls. Do **not** add a memory_events read API or UI in this phase (no consumer yet).

---

## Part D — Tests & verification
Because the new behavior lives in Postgres RPCs (pytest has no live DB, and the existing
confirm tests mock `supabase.rpc`), most verification is **manual**:
- **Automated:** the full existing suite must stay green — the confirm RPC *signatures* are
  unchanged, so the mocked confirm/route tests still pass. `pytest -q`, `npm run lint`,
  `npx tsc --noEmit`, `npm run build`, `git diff --check`. Add no fragile DB-network tests.
- **Manual (user, after applying 0010 + 0011 with their owner UUID filled in):**
  1. Confirm a task / expense / food / calendar item → a matching `memory_events` row exists
     (`domain`, `source_table`, `source_id`, compact `payload_json`).
  2. Trigger a confirm that *fails* its idempotency guard → **no** new `memory_events` row
     (atomic rollback).
  3. Click "Snapshot today" twice → exactly **one** `snapshot_created` event for that date.
  4. New captures/domain rows have `owner_id` set (default works).
  5. Anon key cannot read `memory_events` (RLS backstop, like 0008).

---

## Part E — Docs to update
- `docs/roadmap.md` — Phase 15b (owner_id contract + memory_events populated-at-confirm;
  daily_summaries/embedding_queue/vector explicitly deferred).
- `docs/data-model.md` — `owner_id` on all tables; the `memory_events` append-only log and the
  memory flow it begins.
- `docs/architecture.md` — where memory_events sits in the pipeline (confirmed record →
  memory_event → future embedding).
- `services/api/README.md` — migrations `0010`/`0011`, manual application note, test count.

---

## Out of scope (do NOT build)
`daily_summaries`, `embedding_queue`, embeddings, pgvector, any vector/LLM code, a
memory_events API or UI, per-user RLS policies, multi-user, deployment.

## Key risks (flag for Codex)
- **Editing the confirm RPCs is the sensitive part.** Preserve their existing behavior exactly
  (atomicity, idempotency guards, `SELECT ... FOR UPDATE`, RAISE conditions). The
  `memory_events` insert is purely additive and must be the last statement before `return`,
  inside the same transaction. If in doubt about a function's current body, inspect its
  migration and stop to ask rather than guess.
- **`<OWNER_USER_ID>` placeholder** must be filled by the user before applying — call this out
  prominently in both migrations and the README.
- Keep `payload_json` compact and free of secrets/full account numbers (snapshot payload uses
  already-masked totals; never embed raw broker responses).

---

## Prompt to Codex: Implement Phase 15b

> **Model: 5.5 · Effort: high.** Implement **Phase 15b — memory-ready foundation** per
> `docs/phase-15b-plan.md`. Do not make architectural decisions; if a confirm RPC's current
> body is unclear, stop and ask. **Scope:** `owner_id` on all existing tables + an append-only
> `memory_events` table populated atomically inside the confirm and snapshot RPCs. **No
> daily_summaries, no embedding_queue, no embeddings/vector, no API/UI, no app code changes.**
>
> **Inspect first:** `supabase/migrations/0002_tasks.sql`, `0003_money_events.sql`,
> `0006_food_logs.sql`, `0007_calendar_intents.sql` (the four confirm RPC bodies),
> `0008_rls_lockdown.sql` (RLS pattern), `0009_portfolio_snapshots.sql` (the snapshot RPC +
> existing `owner_id` usage).
>
> **Migration `0010_owner_id.sql`:** add `owner_id text` to `capture_events`, `inbox_items`,
> `agent_runs`, `tasks`, `money_events`, `food_logs`, `calendar_intents` — backfill to
> `'<OWNER_USER_ID>'`, set that as default, set NOT NULL. Top-of-file comment telling the user
> to replace the placeholder with their owner UUID.
>
> **Migration `0011_memory_events.sql`:** create the `memory_events` table (schema in the plan)
> with indexes + RLS enable/force + revoke anon/authenticated. `CREATE OR REPLACE` the four
> confirm RPCs (unchanged signatures), preserving their exact logic, adding an atomic
> `memory_events` insert (`event_type='confirmed'`, compact per-domain `payload_json`,
> `source_table`/`source_id`) as the final step before return. `CREATE OR REPLACE`
> `create_portfolio_snapshot` to upsert one `snapshot_created` event per snapshot id.
>
> **No application code changes.** Update `docs/roadmap.md`, `docs/data-model.md`,
> `docs/architecture.md`, `services/api/README.md`.
>
> **Run:** `pytest -q` (all green — confirm signatures unchanged), `npm run lint`,
> `npx tsc --noEmit`, `npm run build`, `git diff --check`. Report results + the manual steps
> (apply 0010/0011 with owner UUID; confirm an item → memory_event exists; failed confirm →
> none; double snapshot → one event).
>
> **Do NOT touch:** `require_user`/auth, the broker adapters, route logic, or confirm-RPC
> behavior beyond the additive insert. Do not apply migrations.
>
> **Acceptance criteria:** every existing table has a non-null `owner_id` (default-filled);
> `memory_events` exists, RLS-locked; confirming any domain item writes exactly one atomic
> `memory_events` row; a failed confirm writes none; a re-run snapshot keeps one
> `snapshot_created` event/day; full test suite + lint/tsc/build green.
