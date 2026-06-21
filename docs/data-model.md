# Data Model

Database entities for the AI personal assistant. The three core pipeline entities below
are implemented as of Phase 2 — see `supabase/migrations/0001_capture_pipeline.sql`. The
domain and future entities remain conceptual and are built per-module in later phases.

The entities are organised in pipeline order: capture first, domain records last.

---

## Core pipeline entities

> Implemented in Phase 2 (`supabase/migrations/0001_capture_pipeline.sql`). The field
> lists below match the actual migration. There is no `user_id` column yet — the system
> is single-user until auth/RLS arrives in Phase 15.

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

### `investment_notes` — Phase 14+

Confirmed investment notes and intended transactions.

**Key fields:**
- `id`, `inbox_item_id` (FK), `user_id`
- `ticker` — e.g. `CSPX`, `ES3`, `BTC`
- `action_intent` — `buy`, `sell`, `note` (what the user intends or noted)
- `amount` — optional (e.g. $350)
- `currency`
- `notes` — free text
- `created_at`

**Why action_intent and not a transaction:**
This is a note about an intended or planned action — not an executed trade. The system
never executes financial transactions. Investment notes are for tracking your thinking,
not for automating trades.

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

**Deferred to Phase 15.** Plain SQL queries cover 80% of use cases. Add vector memory
when you need to ask questions across a year of data, not a week.
