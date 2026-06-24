# Data Model

Database entities for the AI personal assistant. The three core pipeline entities below
are implemented as of Phase 2 — see `supabase/migrations/0001_capture_pipeline.sql`. The
domain and future entities remain conceptual and are built per-module in later phases.

The entities are organised in pipeline order: capture first, domain records last.

---

## Core pipeline entities

> Implemented in Phase 2 (`supabase/migrations/0001_capture_pipeline.sql`). Phase 15b migration
> `0010_owner_id.sql` adds a default-filled, non-null `owner_id` to these tables. The system
> remains single-owner; this does not introduce multi-user policies.

### `capture_events`

The durable raw input history. Every message, voice note, or typed input creates one row.
Raw source fields are immutable ground truth. Processing fields such as `transcript`,
`processing_status`, and safe metadata may be updated as later pipeline steps run.

**Columns:**
- `id` — UUID primary key (`gen_random_uuid()`)
- `source` — where it came from, e.g. `telegram_text`, `telegram_voice`, `web_form` (not null)
- `source_message_id` — external id from the source system (e.g. Telegram message id), for dedupe/trace
- `raw_text` — the original text exactly as received (null for voice until transcribed)
- `transcript` — speech-to-text transcript for voice captures (Phase 10+)
- `audio_file_id` — reference to the stored original audio file (voice only)
- `processing_status` — where the capture is in the AI pipeline: `received` / `transcription_failed` / `classified` / `classification_failed` / `invalid_ai_output` (not null, default `received`, CHECK-constrained; `transcription_failed` added by migration 0004)
- `metadata` — JSONB for source-specific context and safe error metadata (not null, default `{}`)
- `created_at` — when the capture arrived, UTC (not null, default `now()`)

**Why it exists:** The raw capture is the ground truth. If the AI misclassifies something,
the original capture_event still exists and can be reprocessed. Nothing downstream can
corrupt or lose the original input. The capture is written **before** any AI work, so a
failure in classification never loses the input.

---

### `inbox_items`

Processed items awaiting or recording user review. Every capture_event that goes through
the AI classification pipeline produces one inbox_item. This is the only mutable core
table — `updated_at` is maintained automatically by a trigger.

**Columns:**
- `id` — UUID primary key (`gen_random_uuid()`)
- `capture_event_id` — required FK to `capture_events`
- `item_type` — `task` / `finance` / `calendar` / `food` / `investment` / `note` / `journal` / `unknown` (not null, CHECK-constrained). **`classification_failed` is NOT a value here** — it is a `processing_status` on `capture_events`.
- `review_status` — `pending` / `needs_manual_classification` / `confirmed` / `rejected` (not null, default `pending`, CHECK-constrained)
- `title` — short human-readable summary
- `body` — longer free-text detail
- `structured_json` — JSONB of the structured fields extracted for the item type (not null, default `{}`)
- `confidence` — numeric, AI confidence 0–1 (null if not classified, CHECK-constrained)
- `reviewed_at` — when the user confirmed or rejected the item (null until reviewed)
- `created_at` — not null, default `now()`
- `updated_at` — not null, default `now()`, auto-advanced on every UPDATE by the `set_updated_at()` trigger

Review timestamp constraints require `reviewed_at` to be null while an item is pending or
needs manual classification, and non-null after confirmation or rejection. An item in
`needs_manual_classification` must have `item_type = unknown`.

**`structured_json` shape by item type:**

```
task:
  { title, due_date, urgency (today/this_week/someday), notes }

finance:
  { amount, currency, direction (expense/income), merchant, category, occurred_at, notes }

food:
  { description, meal_type (breakfast/lunch/dinner/snack), logged_at }

calendar:
  { title, proposed_datetime, location, notes }

investment:
  { ticker, action_intent (buy/sell/note), amount, currency, notes }

journal:
  { content, mood }

note:
  { content, tags }
```

**Why it exists:** The inbox is the review gate. Nothing becomes a domain record until
a user explicitly confirms a valid pending row. When its domain module exists, the domain
record and `review_status = confirmed` transition occur in one transaction.

**Review-state audit:** A single `reviewed_at` timestamp plus `review_status` captures the
review outcome — there are no separate `confirmed_at` / `rejected_at` columns. `review_status`
tells you whether the item was confirmed or rejected; `reviewed_at` tells you when.

**Idempotency:** Domain tables (later phases) enforce uniqueness on `inbox_item_id`, and
the review-state transition is applied only once. Together, one inbox_item produces at most
one domain record, regardless of how many times the user clicks Confirm.

**Confirmed without a domain record:** An inbox_item can be confirmed even if no domain
module exists yet for its item type. In this case, `review_status` becomes `confirmed`,
`reviewed_at` is recorded, and no domain table references the row. Introducing the module
later does not automatically backfill these items; retroactive backfill is optional future
or administrative work and is not required by the module phase.

**Transcription failure (Phase 10+):** For voice captures, `transcription_failed` is a
distinct `processing_status` set when the Whisper download or transcription step fails —
before classification is attempted. The inbox_item is marked `needs_manual_classification`
and no classifier `agent_runs` row is written. Classification failure and transcription
failure are always distinguishable by `processing_status` alone.

**Classification failure:** `classification_failed` is a `processing_status` on
`capture_events`, never an `item_type`. If classification fails or returns invalid
structured data, the raw capture remains unchanged (with `processing_status` set to
`classification_failed` or `invalid_ai_output`) and the inbox_item uses
`item_type = unknown` and `review_status = needs_manual_classification`. Safe error
metadata is stored in `capture_events.metadata` / `inbox_items.structured_json`, with full
detail in `agent_runs.error_json`. The dashboard shows the item, but it cannot be confirmed
directly. The user must choose a valid item type and provide valid structured data, which
returns the item to `review_status = pending` before normal confirmation or rejection.

---

### `agent_runs`

A log of every AI model call made by the backend. Append-only.

**Columns:**
- `id` — UUID primary key (`gen_random_uuid()`)
- `capture_event_id` — FK to `capture_events` (null if the call was not tied to a specific capture)
- `inbox_item_id` — FK to `inbox_items` (null if the call did not produce/update a specific item)
- `agent_name` — logical name of the agent/step, e.g. `classifier`, `transcriber` (not null)
- `model` — model identifier, e.g. `claude-sonnet-4-6`, `whisper-1`
- `input_json` — safe summary of the call input, not necessarily the full prompt (not null, default `{}`)
- `output_json` — safe summary of the call output (not null, default `{}`)
- `error_json` — error detail when the call failed (null on success)
- `created_at` — not null, default `now()`

**Why it exists:** Transparency and debugging. Every AI call is logged so you can audit
what the system did and diagnose misclassifications or failed processing.

`capture_events` provide immutable raw input history. `agent_runs` cover AI call audit.
User review audit is covered by `inbox_items.review_status` and `reviewed_at`. A richer
`audit_log` or `inbox_review_events` table with full edit history is explicitly deferred
future work.

---

## Domain entities

These tables store confirmed records. A row is only written when the user confirms an
`inbox_item`. Each row maintains a reference back to the `inbox_item` that created it.

### `tasks` — Phase 8 (implemented, `supabase/migrations/0002_tasks.sql`)

Confirmed action items. Exactly one row per source `inbox_item` (UNIQUE `inbox_item_id`),
written only by the `confirm_task_item` RPC in the same transaction that confirms the item.

**Columns (actual migration):**
- `id` — UUID primary key (`gen_random_uuid()`)
- `inbox_item_id` — required FK to `inbox_items`, **UNIQUE** (idempotency backstop)
- `title` — task description, not null (sourced from the canonical `inbox_items.title`)
- `urgency` — `today` / `this_week` / `someday`, or null. Matches the Phase 6
  `TaskStructuredJson` schema. **`this_month` is intentionally not a value** — the classifier
  and the edit endpoint can never produce it, so it would be dead.
- `due_date` — **text**, nullable. Stores the AI's free-text date verbatim (e.g. "next
  Friday"); not parsed to a real date in Phase 8.
- `notes` — free text, nullable
- `status` — `open` / `completed` (not null, default `open`, CHECK-constrained)
- `completed_at` — timestamptz, null while open; CHECK ties it to `status`
- `created_at`, `updated_at` — not null, default `now()`; `updated_at` auto-advanced by the
  shared `set_updated_at()` trigger

No `user_id` (single-user until Phase 15) and no `tags` (not in the Phase 6 task schema).
These remain possible future additions, not part of the Phase 8 MVP.

---

### `money_events` — Phase 9 (implemented, `supabase/migrations/0003_money_events.sql`)

Confirmed finance records. Exactly one row per source `inbox_item` (UNIQUE `inbox_item_id`),
written only by the `confirm_finance_item` RPC in the same transaction that confirms the item.
Immutable in Phase 9 (no edit/delete) — hence no `updated_at`.

**Columns (actual migration):**
- `id` — UUID primary key (`gen_random_uuid()`)
- `inbox_item_id` — required FK to `inbox_items`, **UNIQUE** (idempotency backstop)
- `amount` — numeric, not null, **CHECK `amount > 0`**
- `currency` — text, not null (e.g. `SGD`, `USD`; default `SGD` from the classifier)
- `direction` — `expense` / `income`, CHECK-constrained
- `merchant`, `category`, `notes` — text, nullable
- `occurred_at` — **text**, nullable. The AI's free-text date verbatim (e.g. "yesterday");
  not parsed to a timestamp in Phase 9. Finance views order by `created_at`.
- `created_at` — not null, default `now()`

**Income decision (Phase 9):** `direction` permits both values (to match this model and
avoid a future widen-migration), but Phase 9 **only creates expense rows**.
`confirm_finance_item` hard-requires `direction='expense'`. A finance **income** item confirms
via the Phase 7 **status-only** path (`review_status='confirmed'`, `reviewed_at` set, no
`money_event`) — income's module does not exist yet, so (like pre-Phase-8 task items) it is
**not backfilled** when income support later lands.

No `user_id` (single-user until Phase 15). Totals in the `/finance` view are grouped by
currency, then category — amounts in different currencies are never summed.

---

### `food_logs` — Phase 11 (implemented, `supabase/migrations/0006_food_logs.sql`)

Confirmed food records. Exactly one row per source `inbox_item` (UNIQUE `inbox_item_id`),
written only by the `confirm_food_item` RPC in the same transaction that confirms the item.
Immutable in Phase 11 (no edit/delete) — hence no `updated_at`.

**Columns (actual migration):**
- `id` — UUID primary key (`gen_random_uuid()`)
- `inbox_item_id` — required FK to `inbox_items`, **UNIQUE** (idempotency backstop)
- `description` — what was eaten, **not null** (sourced from `FoodStructuredJson.description`)
- `meal_type` — `breakfast` / `lunch` / `dinner` / `snack`, nullable, CHECK-constrained
- `logged_at` — **text**, nullable. The AI's free-text date/time verbatim (e.g. "lunchtime",
  "this morning"). **Not parsed.** Not used for date filtering — display only.
- `created_at` — not null, default `now()`
- **Phase 17 additions** (`supabase/migrations/0012_food_nutrition.sql`): `calories`,
  `protein_g`, `carbs_g`, `fat_g` (nullable `numeric`, AI-estimated, user-editable in review)
  and `image_path` (nullable text — object path in the private `food-photos` Storage bucket).
  Photo captures set `capture_events.image_path` (the raw photo, parallel to `audio_file_id`);
  `confirm_food_item` copies it onto the food log. The frontend receives short-lived signed URLs,
  never the raw path. Estimates apply to both photo and text food captures.

**"Today" filtering contract:**
`GET /food_logs?date=today` returns logs whose `created_at` falls within the user's local
calendar day. "Today" = the calendar day in which the item was *confirmed*, computed in the
user's `USER_TIMEZONE` (IANA string, e.g. `"Asia/Singapore"`). Local midnight boundaries are
computed at request time and converted to UTC:
```
created_at >= local_midnight_utc  AND  created_at < next_local_midnight_utc
```
A meal confirmed at 11:59 PM SGT appears in today's view. `logged_at` is not queryable in
Phase 11 — it is a display field only.

No `user_id` (single-user until Phase 15). No `estimated_calories`, `estimated_protein_g`,
or `notes` — the classifier does not extract these fields in Phase 11.

---

### `calendar_intents` — Phase 12 (implemented, `supabase/migrations/0007_calendar_intents.sql`)

Confirmed calendar intentions. Exactly one row per source `inbox_item` (UNIQUE `inbox_item_id`),
written only by the `confirm_calendar_item` RPC in the same transaction that confirms the item.
Immutable in Phase 12 (no edit/delete) — hence no `updated_at`. These are NOT live calendar
events — calendar sync is deferred to a future phase requiring OAuth and conflict detection.

**Columns (actual migration):**
- `id` — UUID primary key (`gen_random_uuid()`)
- `inbox_item_id` — required FK to `inbox_items`, **UNIQUE** (idempotency backstop)
- `title` — event title as extracted by the AI, **not null**
- `proposed_datetime` — **text**, nullable. The AI's free-text proposed time verbatim
  (e.g. "next Friday 7pm"). **Not parsed.** Display only — ordering uses `created_at`.
- `location` — optional location as extracted by the AI, nullable
- `notes` — optional notes as extracted by the AI, nullable
- `created_at` — not null, default `now()`

**Key decisions (Phase 12):**
- No `user_id` (single-user until Phase 15)
- No `status` column (`draft`/`synced` deferred until calendar sync exists)
- `proposed_datetime` stored as TEXT — verbatim AI output, same pattern as `occurred_at`
  and `logged_at`
- Display order: `created_at DESC` (confirmation time); no meaningful sort by event time
  without a parsed datetime

**Why `calendar_intents` and not direct calendar events:**
Creating a real calendar event is a sensitive, irreversible action. Phase 12 adds the
ability to capture and review calendar intentions. Actual calendar sync requires OAuth,
conflict detection, and a more deliberate confirmation UX — deferred to a later phase.

---

### `exercise_logs` — Phase 18 (implemented, `supabase/migrations/0013_exercise_logs.sql`)

Confirmed exercise/workout records. Exactly one row per source `inbox_item` (UNIQUE
`inbox_item_id`), written only by the `confirm_exercise_item` RPC in the same transaction that
confirms the item and appends one `memory_events` row (Phase 15b contract). Immutable in Phase 18
(no edit/delete) — hence no `updated_at`.

**Columns (actual migration):**
- `id` — UUID primary key (`gen_random_uuid()`)
- `inbox_item_id` — required FK to `inbox_items`, **UNIQUE** (idempotency backstop)
- `owner_id` — text, **not null**, default-filled single-owner (matches 0010/0011)
- `activity` — what was done, **not null** (e.g. "running", "gym - chest")
- `duration_min`, `distance_km`, `calories` — nullable `numeric` (AI-extracted/estimated,
  user-editable in review; finite & non-negative validators on the classifier schema)
- `sets`, `reps` — nullable `integer`
- `intensity` — nullable text, free-form (e.g. "easy"/"moderate"/"hard") — not constrained
- `logged_at` — **text**, nullable. The AI's free-text date/time verbatim. **Not parsed.** Not
  used for date filtering — display only (same pattern as `food_logs.logged_at`).
- `notes` — nullable text
- `created_at` — not null, default `now()`

**"Today" filtering contract:** identical to `food_logs` — `GET /exercise_logs?date=today`
filters on `created_at` within the user's `USER_TIMEZONE` calendar day; `logged_at` is display
only. `GET /exercise_logs` also returns `totals` (summed `duration_min`, `distance_km`,
`calories`). RLS is deny-by-default; only the service-role backend reads/writes.

---

### `habits` — Phase 20 (implemented, `supabase/migrations/0015_habits_goals.sql`)

Confirmed habit **definitions**. One row per source `inbox_item` (UNIQUE `inbox_item_id`), written
only by `confirm_habit_item` in the same transaction that confirms the item and appends one
`memory_events` row (`domain='habit'`, payload `{name, cadence, target}`). **Definition-only in
Phase 20** — no check-ins, streaks, recurrence, or reminders; immutable, so no `updated_at`.

**Columns:** `id`, `inbox_item_id` (UNIQUE FK), `owner_id` (default-filled, not null), `name`
(not null), `cadence` (free text e.g. "daily" — **not** enum-constrained, **not** a scheduler),
`target` (text), `notes` (text), `created_at`. RLS deny-by-default; service-role only.

### `goals` — Phase 20 (implemented, `supabase/migrations/0015_habits_goals.sql`)

Confirmed goals. One row per source `inbox_item` (UNIQUE `inbox_item_id`), written only by
`confirm_goal_item` (appends one `memory_events` row, `domain='goal'`, payload
`{title, target, target_date, status}`). **`status` is the only field mutable after confirmation**
(`active` / `achieved` / `abandoned`) via `PATCH /goals/{id}/status`, mirroring `tasks.complete`.
**Status changes do NOT write `memory_events`** — the 15b contract logs confirmations/snapshots
only.

**Columns:** `id`, `inbox_item_id` (UNIQUE FK), `owner_id` (default-filled, not null), `title`
(not null), `description` (text), `target` (free-text target/metric — no numeric split this
phase), `target_date` (**text**, verbatim AI date, not parsed), `status` (CHECK
active/achieved/abandoned, default `active`), `created_at`, `updated_at` (via the shared
`set_updated_at()` trigger). RLS deny-by-default; service-role only.

> Migration `0015` also **widens the `inbox_items.item_type` CHECK** to include `habit` and `goal`
> (required for any new item_type — see the Phase 18 `exercise` precedent).
>
> **Phase 22b-2 extension (`0018_goal_financial_target.sql`):** `goals` gains `target_value`
> (numeric, CHECK ≥0), `target_currency` (text), and `target_metric`
> (`net_worth`|`liquid_cash`|`invested`|`broker_total`, null → net_worth). A goal is a **financial
> goal** iff `target_value` + `target_currency` are set; `confirm_goal_item` is replaced to persist
> them. `GET /financial_intelligence/financial-goals` computes `progress_pct = base_value /
> target_value` (base = the chosen metric in the goal's currency, via `compute_summary`), per
> currency, no FX. **No attribution / activity-linking / projections** (broad attribution → Phase 25).

---

### `decisions` — Phase 21 (implemented, `supabase/migrations/0016_decisions.sql`)

Confirmed decision-journal entries. One row per source `inbox_item` (UNIQUE `inbox_item_id`),
written only by `confirm_decision_item` (appends one `memory_events` row, `domain='decision'`,
payload `{decision, category, confidence, decided_at}`). **`status` is the only field mutable
after confirmation** (`active` / `reversed` / `archived`) via `PATCH /decisions/{id}/status`,
mirroring goals. **Status changes do NOT write `memory_events`.**

**Columns:** `id`, `inbox_item_id` (UNIQUE FK), `owner_id` (default-filled, not null), `decision`
(not null — the choice made), `reason`, `options_considered`, `expected_outcome` (creation-time
expectation only), `confidence` (numeric, the **user's** 0–1 confidence, CHECK-constrained,
distinct from the classifier confidence), `category`, `decided_at` (**text**, verbatim AI date,
not parsed), `status` (CHECK active/reversed/archived, default `active`), `notes`, `created_at`,
`updated_at` (via the shared `set_updated_at()` trigger). RLS deny-by-default; service-role only.

Migration `0016` also **widens the `inbox_items.item_type` CHECK** to include `decision`. **Not
stored yet (deferred):** observed/actual outcome, outcome-review fields, decision-quality score,
`related_goal_id`/attribution (Phase 25), structured options array, decision-tree structure.

---

### `manual_financial_snapshots` — Phase 22a (implemented, `supabase/migrations/0017_financial_snapshots.sql`)

Reviewed manual financial inputs that feed the deterministic Financial Intelligence layer. One row
per source `inbox_item` (UNIQUE `inbox_item_id`), written only by `confirm_financial_snapshot_item`
(appends one `memory_events` row, `domain='financial_snapshot'`, payload `{as_of}`). **Immutable** —
latest by `created_at` is "current"; update by capturing a new one (no status, no edit endpoint).

**Columns:** `id`, `inbox_item_id` (UNIQUE FK), `owner_id` (default-filled, not null), `as_of`
(**text**, verbatim, not parsed), `monthly_income_json` / `monthly_investment_json` /
`liquid_cash_json` / `liabilities_json` (jsonb arrays of `{currency, amount}`, default `[]`, each
CHECK `jsonb_typeof = 'array'` — Pydantic `FinancialSnapshotStructuredJson` is the real shape
guard), `notes`, `created_at`. RLS deny-by-default; service-role only. Migration `0017` also widens
`inbox_items.item_type` for `financial_snapshot`.

> **`liquid_cash` is NON-broker cash** (bank/CPF). Broker cash + positions come from the portfolio
> snapshot's `total_value`; keeping them separate avoids double counting in net worth.

**Financial Intelligence metrics (read-only, deterministic — no table):** `GET
/financial_intelligence/summary` assembles per-currency metrics via the pure `compute_summary()`
(`app/services/financial_intelligence.py`): net worth = `liquid_cash + broker_total − liabilities`
(present components only, with `complete`/`missing`), invested/broker from the latest portfolio
snapshot ("as of `<snapshot_date>`" + partial flag), monthly income/investment from the manual
snapshot, **logged** monthly expenses + trailing-3-mo average from `money_events` (filtered by
`created_at` in USER_TIMEZONE month windows — **not** the free-text `occurred_at`), savings rate,
investment rate, cash runway. **Never summed across currencies**; missing inputs → `null`
(unavailable), never estimated. **Not stored yet:** per-account breakdown, FX, the `goals` numeric
target (Phase 22b-2 financial-goal progress).

**Monthly explanation read-model (Phase 22b-1, no schema):** `GET /financial_intelligence/monthly`
(pure `compute_monthly()`) compares the **current vs previous local month** by currency: **logged**
expenses (money_events by `created_at` in USER_TIMEZONE windows; previous only if ≥1 expense
predates the current month, else unavailable — never implied 0), **logged** savings rate (income
from the latest manual snapshot), manual-position change (cash − liabilities between the two latest
manual snapshots, if ≥2), and portfolio `total_value` change (between the two latest portfolio
snapshots, if ≥2, with snapshot dates + partial flag). Deterministic `explanation[]` strings only —
never AI, never cross-currency summed, missing → unavailable.

**Category summary read-model (Phase 22c, no schema):** `GET /financial_intelligence/category-summary`
groups the current local month's confirmed **expense** `money_events` by **currency → category**
(reusing the existing `money_events.category`; null → "uncategorized"; Decimal sums ordered by amount
desc) with per-currency totals. By currency, never cross-currency summed; logged/confirmed expenses
only; no new table.

---

### Portfolio data — Phase 14 (external, read-only)

Phase 14 does not add an `investment_notes` or portfolio-positions table. Current positions,
cash, valuations, and today's performance are read from Tiger Brokers and IBKR on demand. The
broker accounts remain the source of truth.

The backend normalizes broker responses into a stable API shape. Expected position fields
include:
- broker and masked account reference
- broker instrument identifier and display symbol
- quantity and average cost when supplied by the broker
- market price, market value, unrealized P&L, and today's P&L when supplied
- native currency
- quote/data freshness and `as_of` timestamp when available

Cash balances are represented separately and remain grouped by currency. Values in different
currencies are never summed without an explicitly approved FX source.

The existing `investment` inbox classification remains reviewable, but confirming one does not
change portfolio positions or submit an order. Normalized portfolio snapshots are introduced
separately in Phase 14.5; instrument-master persistence, MCP exposure, and broker execution
records remain future entities that require separate designs.

### Portfolio snapshots — Phase 14.5

Portfolio snapshots are daily historical observations of the normalized Phase 14 response.
They are not the source of truth for current positions and are never written by a normal
`GET /portfolio` refresh. A protected manual action creates or refreshes at most one canonical
snapshot per `(owner_id, snapshot_date)`. Scheduling is deferred until deployment.

Migration `0009_portfolio_snapshots.sql` creates:
- `portfolio_snapshots` — owner/date header, source, generated time, partial-failure state,
  and safe broker-status metadata
- `portfolio_snapshot_currency_totals` — native-currency invested, cash, and total values plus
  completeness counts; currencies are never converted or combined
- `portfolio_snapshot_positions` — one normalized atomic row per holding and cash balance,
  including `stable_asset_id`, masked account reference, valuation, P&L, allocation, and metadata

Snapshot rows preserve stable asset identity, masked account labels, native currency,
broker/instrument identifiers, quantities, valuations, P&L and its source, completeness flags,
quote status, broker `as_of`, and snapshot timestamps where available. Raw broker responses,
credentials, sessions, private keys, and full account numbers are never persisted.

Each snapshot is saved transactionally: its run and all child observations commit or roll back
together. The run records completeness and safe broker-level failure state so a missed or expired
session cannot masquerade as a complete zero-position day. Later memory generation should derive
concise facts from validated snapshot history; vector embeddings are not a substitute for
SQL-based numeric analysis. All three tables are RLS-locked, and the service-role-only
`create_portfolio_snapshot` RPC atomically upserts the header and replaces all children.

---

## Ownership and memory events — Phase 15b

Migration `0010_owner_id.sql` adds `owner_id text not null` to `capture_events`, `inbox_items`,
`agent_runs`, `tasks`, `money_events`, `food_logs`, and `calendar_intents`. Existing rows are
backfilled and new rows use the configured owner UUID as their database default. The three
portfolio snapshot tables already include `owner_id`. This is a single-owner ownership contract;
it does not add per-user policies or change application queries.

Migration `0011_memory_events.sql` creates `memory_events`, a compact event backlog for future
memory consumers:

- `id`, `owner_id`, `occurred_at`, `created_at`
- `domain` and `event_type`
- `payload_json` — concise retrieval fields, never a raw domain or broker payload
- `source_table` and `source_id` — link to the durable domain record or snapshot

The four confirmation RPCs append a `confirmed` event only after creating the domain record and
confirming its inbox item, inside the same transaction. If any validation or write fails, the
memory event rolls back with the rest of the confirmation. Existing idempotent confirmation
returns do not append another event. The portfolio snapshot RPC replaces the event linked to its
canonical snapshot during a refresh, keeping one `snapshot_created` event per snapshot.

`memory_events` is RLS-enabled, RLS-forced, and inaccessible to anon/authenticated database
roles. It is append-only by convention. Daily summaries, embedding queues, embeddings, pgvector,
and semantic search remain deferred.

**Timeline read-model (Phase 19).** The Daily Life Timeline (`GET /timeline`, `/timeline` page)
is a read-only projection of `memory_events` — **no domain-table joins**; each event's
`payload_json` already carries the display fields. The payloads written today are:

| `domain` | `event_type` | `source_table` | `payload_json` keys |
|---|---|---|---|
| `task` | `confirmed` | `tasks` | `title, status, due_date` |
| `money` | `confirmed` | `money_events` | `amount, currency, merchant, direction` |
| `food` | `confirmed` | `food_logs` | `description, meal_type, calories, logged_at` |
| `calendar` | `confirmed` | `calendar_intents` | `title, proposed_datetime, location` |
| `exercise` | `confirmed` | `exercise_logs` | `activity, duration_min, distance_km, logged_at` |
| `portfolio_snapshot` | `snapshot_created` | `portfolio_snapshots` | `snapshot_date, partial_failure, currency_totals` |

The timeline orders by `occurred_at desc, id desc` with keyset (cursor) pagination, served by the
existing `idx_memory_events_owner_occurred` index (no new index). It shows **only** these
confirmation/snapshot events, **from Phase 15b onward** — captures, pending, and rejected items
are not included, and pre-15b confirmations are not backfilled. Frontend formatting reads each
payload key defensively (keys may be absent). An optional future index
`(owner_id, domain, occurred_at desc)` can be added if domain-filtered pages grow large.

---

## Future entities

These are conceptual ideas for later phases. Do not implement them yet.

### `user_preferences`

Long-term personal facts and preferences that the assistant should remember across
sessions (e.g. "I prefer term insurance over whole life", "I use SGD as my primary
currency", "My dietary target is 150g protein per day").

**Potential fields:**
- `id`, `user_id`
- `key` — machine-readable identifier (e.g. `diet.protein_target_g`)
- `value` — the preference value
- `source_inbox_item_id` — optional, which capture this preference came from
- `created_at`, `updated_at`

### `memory_chunks`

Vector embeddings for semantic search across past captures (the "Ask my OS" feature).
Uses Supabase pgvector extension.

**Deferred beyond the Phase 15b foundation.** Phase 15b stores compact source events only.
Add vector memory when cross-period semantic recall warrants the extra machinery.
