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
- `processing_status` — where the capture is in the AI pipeline: `received` / `classified` / `classification_failed` / `invalid_ai_output` (not null, default `received`, CHECK-constrained)
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

### `tasks` — Phase 8+

Confirmed action items.

**Key fields:**
- `id`, `inbox_item_id` (FK), `user_id`
- `title` — the task description
- `urgency` — `today`, `this_week`, `this_month`, `someday`
- `due_date` — optional date
- `status` — `open`, `completed`
- `tags` — text array
- `notes` — free text
- `completed_at`, `created_at`, `updated_at`

---

### `money_events` — Phase 9+

Confirmed expense or income records.

**Key fields:**
- `id`, `inbox_item_id` (FK), `user_id`
- `amount` — decimal
- `currency` — ISO code (e.g. `SGD`, `USD`)
- `direction` — `expense` or `income`
- `merchant` — who you paid / who paid you
- `category` — user-defined category (food, transport, entertainment, etc.)
- `occurred_at` — when the transaction happened
- `notes`
- `created_at`

---

### `food_logs` — Phase 11+

Confirmed food entries.

**Key fields:**
- `id`, `inbox_item_id` (FK), `user_id`
- `description` — what was eaten (free text, e.g. "chicken rice and kopi")
- `meal_type` — `breakfast`, `lunch`, `dinner`, `snack`
- `logged_at` — when the meal was eaten (user's local date)
- `estimated_calories` — optional, can be filled by AI estimation later
- `estimated_protein_g` — optional
- `notes`
- `created_at`

---

### `calendar_intents` — Phase 12+

Confirmed calendar intentions. These are NOT live calendar events yet — they are records
of the user's intent to schedule something. Syncing to a real calendar is a future feature.

**Key fields:**
- `id`, `inbox_item_id` (FK), `user_id`
- `title` — event description
- `proposed_datetime` — when the user intends this to happen
- `location` — optional
- `notes`
- `status` — `draft` (confirmed by user but not yet synced) / `synced` (future)
- `created_at`

**Why `calendar_intents` and not direct calendar events:**
Creating a real calendar event is a sensitive, irreversible action that affects your
external schedule. Phase 12 adds the ability to capture and review calendar intentions.
Actual calendar sync is deferred further — it requires OAuth, conflict detection, and a
more deliberate confirmation UX.

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
