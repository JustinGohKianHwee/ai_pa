# Architecture

## Overview

The system is structured as a pipeline with a hard gate in the middle. Data flows in from
capture surfaces, is processed by AI, and is held in a pending state until the user
explicitly confirms it. The dashboard is the review and control surface — not a passive
display.

```
Capture Surface
      │
      ▼
  [Backend API]
  - receive webhook
  - store capture_event
  - call AI (classify + extract)
  - write inbox_item (review_status: pending)
      │
      ▼
  [Supabase: inbox_items]
      │
      ▼
  [Frontend Dashboard]
  - show pending and needs-manual-classification inbox
  - user reviews, edits, confirms/rejects
      │
      ▼
  [Backend API]
  - receive confirmation
  - validate inbox_item item_type, structured_json, and review_status
  - mark confirmed and record reviewed_at
  - if the domain module exists, create exactly one linked domain record
    in the same atomic transaction
      │
      ▼
  [Supabase: domain tables]
```

The pipeline is sequential. No step is skipped. No domain record is written without first
passing through steps 1–4.

---

## Layer 1: Capture

**What it is:** The entry point for all data into the system.

**Capture surfaces (current and planned):**
- Telegram bot — text messages, voice notes (Phase 4/10+), and **food photos** (Phase 17+)
- Dashboard web form — typed input (Phase 5+)
- Future: email, iOS Shortcuts, documents

**What happens here:**
- The raw input arrives at a backend webhook endpoint
- It is written immediately to `capture_events` before any AI work
- If the input is a voice note, it is passed to the transcription layer
- If the input is a **photo**, it is stored in a private Storage bucket and passed to the
  food **vision** layer (`gpt-4o-mini`), which estimates the dish + calories/macros; non-food
  photos route to manual review. The estimate populates the food inbox item and is editable in
  review like any other capture
- The raw text is then passed to the classification layer
- Raw source fields are never modified; transcript, processing status, and safe metadata
  may be updated by later pipeline steps

**Key principle:** Capture is fast and cheap. The system should never lose a capture. Even
if classification fails, the raw capture_event exists and can be reprocessed.

---

## Layer 2: AI Transcription

**What it is:** Converts voice notes to text before classification.

**Technology:** OpenAI Whisper

**What happens here:**
- Telegram delivers voice notes as OGG audio files
- The backend downloads the audio and sends it to Whisper
- Whisper returns a text transcript
- The transcript is stored on the capture_event and passed to classification

**Note on audio format:** Telegram voice notes are OGG format. Whisper accepts this but
requires the correct MIME type (`audio/ogg`). Do not pass the wrong content-type.

Transcription is currently pinned to English (`language="en"`) to prevent incorrect automatic
language detection. Voice transcription was implemented and manually verified in Phase 10.

---

## Layer 3: AI Classification and Extraction

**What it is:** The AI brain that interprets natural language and extracts structured data.

**Technology:** OpenAI (`gpt-4o-mini`) — approved primary classifier as of Phase 6.

**What happens here:**
- The raw text is sent to OpenAI with a structured system prompt
- OpenAI returns a JSON object containing:
  - `item_type`: what kind of item this is (task / finance / calendar / food / investment / note / journal / unknown)
  - `structured_json`: structured fields relevant to that type (amount, date, merchant, due_date, urgency, etc.)
  - `confidence`: how confident the AI is in its classification
  - `summary`: a short human-readable summary of what was captured

**Key rule: Page loads never trigger AI calls.**
AI classification happens once, when the capture is first received. Reading the inbox
does not trigger any AI. Only new captures trigger classification.

**Key rule: Validate AI output before storing.**
The AI can hallucinate field values (e.g. a date that does not make sense, an entity ID
that does not exist). Always validate extracted data before writing to the database.

**Failure behavior**

Raw `capture_events` are written before any AI work begins. If AI classification fails
for any reason, the capture is never lost.

If OpenAI returns an error, times out, or returns invalid structured output:
- The `capture_event` already exists and its raw source fields are unaffected
- An `inbox_item` is created with `item_type = "unknown"`,
  `review_status = "needs_manual_classification"`; the linked capture_event's
  `processing_status` is set to `classification_failed` or `invalid_ai_output`
- `structured_json` is set to `{}`; safe error metadata may be retained separately
- An `agent_runs` row is written with the error detail
- The item appears in the dashboard review inbox
- The user must manually choose a valid `item_type` and provide valid structured data;
  the item then returns to `review_status = "pending"` before it can be confirmed
- No domain record is created

If AI returns structurally valid JSON but with invalid field values (e.g. a wrong field
name, a disallowed urgency literal, a missing required field):
- The backend validates `structured_json` against a per-type Pydantic schema with
  `extra="forbid"` — unknown or misspelled fields cause immediate rejection
- If validation fails, the item receives `review_status = "needs_manual_classification"`,
  the linked `capture_event` receives `processing_status = "invalid_ai_output"`, and an
  `agent_runs` row is written with the error detail
- The user must manually correct the `item_type` and `structured_json` fields via the
  Edit controls; when a valid, non-unknown type and valid data are saved the item
  transitions to `review_status = "pending"` and can then be confirmed

---

## Layer 4: Pending Inbox

**What it is:** The review gate. All classified items live here until the user acts.

**Storage:** `inbox_items` table in Supabase

**What an inbox_item contains:**
- Required reference to the original `capture_event`
- `item_type` — `task`, `finance`, `calendar`, `food`, `investment`, `note`, `journal`, or `unknown`
- `title` and `body` — human-readable summary and detail
- `structured_json` — the structured fields the AI extracted (JSONB)
- `confidence` — AI confidence from 0 to 1, or null when not classified
- `review_status` — `pending`, `needs_manual_classification`, `confirmed`, or `rejected`
- `created_at`, `updated_at`, and `reviewed_at` timestamps

Technical `processing_status` belongs to the linked `capture_event`, not the inbox item.

**What the user sees:**
- All items where `review_status` is `pending` or `needs_manual_classification`
- For each item: the original raw text, item type, processing state, and extracted fields
- Edit controls to correct any field before confirming
- Confirm / Reject buttons

**What the user can do:**
- Edit the extracted data (e.g. correct a wrong date or amount)
- Change the item type (e.g. reclassify a note as a task)
- Confirm — triggers the atomic confirmation operation (see below)
- Reject — marks the item as rejected, records `reviewed_at`, and writes no domain record

**Atomicity and idempotency**

Confirmation is a single atomic operation. When the user confirms an item:
1. The backend validates the inbox_item exists and has `review_status = pending`
2. The backend validates its `item_type` and `structured_json`
3. If a domain module exists for the type, the backend creates exactly one linked domain
   record, marks the inbox_item confirmed, and records `reviewed_at` in one transaction
4. If no domain module exists yet for the type, the same user-review transaction only
   marks the inbox_item confirmed and records `reviewed_at`
5. There is never a visible state where a domain record exists while its inbox_item remains pending
6. Confirmation is idempotent: re-submitting a confirm on an already-confirmed item
   returns the existing result and does not create a second domain record
7. Domain tables enforce uniqueness on `inbox_item_id`
8. `needs_manual_classification` items cannot be confirmed directly; they must first be
   manually corrected and returned to `review_status = pending`

---

## Layer 5: Confirmed Domain Modules

**What it is:** The final resting place for confirmed data, separated by domain.

**Tables:**
- `tasks` — confirmed tasks (Phase 8+)
- `money_events` — confirmed expenses and income (Phase 9+)
- `food_logs` — confirmed food entries (Phase 11+)
- `calendar_intents` — confirmed calendar intentions (Phase 12+)
- `exercise_logs` — confirmed workouts (Phase 18+)
- `habits` — confirmed habit definitions (Phase 20+)
- `goals` — confirmed goals; status mutable post-confirm (Phase 20+)
- `decisions` — confirmed decision-journal entries; status mutable post-confirm (Phase 21+)
- `manual_financial_snapshots` — reviewed manual financial inputs, immutable (Phase 22a+)

**Key principle:** A domain record is only written when:
1. The user explicitly triggered confirmation on a valid pending inbox_item
2. The domain record and `review_status = confirmed` transition occur atomically
3. The domain record links uniquely to the source `inbox_item`

Items confirmed before their domain module exists remain confirmed inbox_items only.
Introducing a module does not implicitly backfill them.

Each domain module has its own view in the dashboard. The dashboard's home screen is the
inbox; domain views are secondary screens.

---

## Layer 6: Audit coverage

**Raw input history — `capture_events`:**
Every raw capture is stored before AI work. Its raw source fields remain ground truth while
technical processing fields may advance.

**AI call audit — `agent_runs` (Phase 2+):**
Every AI model call is recorded in `agent_runs` with optional capture/inbox references,
`agent_name`, model, safe input/output JSON, error JSON, and creation time. This is the
transparency log for AI work, including classification failures.

**User review audit — inbox_item state and timestamp:**
The `inbox_items` table carries `review_status` and `reviewed_at`. Together they record
the user's decision and when it occurred.
No separate user-action table is needed for the early phases.

**Richer audit log (deferred):**
A separate `audit_log` or `inbox_review_events` table — capturing full edit history,
field-level changes before confirmation, and reversions — is a valid future addition
but is not needed until the review loop is stable. It will be introduced after Phase 8
if the user decides richer audit detail is needed. Do not create this table before then.

---

## Layer 7: Frontend Dashboard

**What it is:** The user's interface for review and control.

**Technology:** Next.js 15, App Router, TypeScript, Tailwind CSS

**Primary screen:** The review inbox — pending and needs-manual-classification items with
edit, Confirm, and Reject controls.

**Secondary screens (added per phase):**
- Tasks list (Phase 8+)
- Finance view (Phase 9+)
- Food log view (Phase 11+)
- Calendar intents view (Phase 12+)
- Daily review (Phase 13+)
- Read-only portfolio view aggregating Tiger and IBKR (Phase 14+)
- Daily portfolio snapshot status/history (Phase 14.5+)
- Exercise log view (Phase 18+)
- Daily Life Timeline — read-only chronological feed over `memory_events` (Phase 19+)
- Habits and Goals views (Phase 20+)
- Decision Journal view (Phase 21+)
- Financial Intelligence — deterministic per-currency metrics + monthly explanation + financial-goal progress, no AI numbers (Phase 22a/22b+)

**Key principle:** The frontend never calls AI directly. It reads from Supabase (for
confirmed domain data) and calls backend API endpoints (for capture and confirmation actions).

---

## Layer 8: Backend API

**What it is:** The backend service that handles all non-trivial logic.

**Technology:** FastAPI + Python

**Responsibilities:**
- Receive Telegram webhook events
- Call AI (classification, transcription)
- Write capture_events and inbox_items to Supabase
- Handle confirmation actions from the dashboard
- Write domain records when items are confirmed
- Preserve immutable `capture_events`, write `agent_runs`, and record inbox review state and timestamps

**Key principle:** The backend is the only thing that calls AI. The frontend never calls
AI APIs directly.

**Deployed as:** A separate Python service (Render / Railway / Fly — Phase 16+).
During development: runs locally alongside the Next.js dev server.

**Authentication and route security (Phase 15a+)**

- Supabase Auth provides the owner's email/password session. Next.js stores and refreshes
  the session in cookies and forwards the access token to FastAPI.
- Every non-webhook protected API route verifies the ES256 signature through Supabase's
  cached public JWKS, then checks the authenticated audience, expiry, and
  `sub == OWNER_USER_ID` before serving personal data.
- The Telegram webhook path (`/telegram/webhook`) is the only route that should ever
  be exposed publicly. It must validate `X-Telegram-Bot-Api-Secret-Token` before
  accepting any payload.
- Tunneling exposes routes publicly but does not bypass JWT or webhook-secret checks.
- `SUPABASE_SERVICE_ROLE_KEY` is used only server-side. It must never appear in
  frontend environment variables, browser bundles, or client-visible responses.
- The frontend anon key is public-safe, but RLS and revoked grants prevent direct table
  and confirmation-RPC access. FastAPI retains the service-role client by design.

---

## Layer 9: Supabase Database

**What it is:** The persistent data store.

**Technology:** Supabase Postgres

**Tables (see `docs/data-model.md` for full descriptions):**
- `capture_events`
- `inbox_items`
- `agent_runs`
- `tasks` (Phase 8+)
- `money_events` (Phase 9+)
- `food_logs` (Phase 11+)
- `calendar_intents` (Phase 12+)
- `portfolio_snapshots`, `portfolio_snapshot_currency_totals`, and
  `portfolio_snapshot_positions` (Phase 14.5+)
- `memory_events` — compact events written atomically by confirmation and snapshot RPCs
  (Phase 15b+)
- `user_preferences` (Phase 15+)
- `memory_chunks` — future vector embeddings (deferred beyond Phase 15b)

**Auth / RLS:** Phase 15a adds single-owner API authentication and deny-by-default RLS on
all current tables. The service-role backend bypasses RLS only after API-layer JWT checks.

**Memory-ready flow:** Phase 15b adds a common default-filled `owner_id` contract and extends
the existing database RPC transactions as follows:

`confirmed inbox item → domain record + memory_event`

Portfolio snapshot creation similarly writes or replaces one `snapshot_created` memory event.
`memory_events` is an append-only-by-convention source backlog for future summaries or
embeddings; it is not itself a vector store. Failed confirmation transactions leave no domain
record and no memory event.

**First read consumer (Phase 19):** the Daily Life Timeline (`GET /timeline`) reads
`memory_events` directly — read-only, no AI, no domain joins, keyset-paginated — projecting each
event's `payload_json` into a chronological feed. See `docs/data-model.md` for the payload→display
mapping. Vector embeddings over `memory_events`/summaries remain deferred beyond Phase 15b.

---

## Layer 10: Future Integrations

These are not in scope until the core pipeline is working.

- **Tiger/IBKR portfolio aggregation** — read-only broker adapters and normalized portfolio
  view (Phase 14)
- **Portfolio snapshots** — manually triggered, transactional normalized observations in
  Supabase, idempotent per owner/local day, for later SQL analysis and memory derivation
  (Phase 14.5). Scheduling is deferred until deployment.
- **Broker MCP tools** — expose normalized read-only portfolio capabilities after the adapter
  contract is stable
- **Broker execution** — future high-risk workflow requiring order preview, a separate explicit
  execution confirmation, idempotency, broker order audit, and reconciliation
- **Google Calendar** — sync confirmed `calendar_intents` to a real calendar event
- **Email capture** — parse emails as capture events
- **iOS Shortcuts** — alternative capture surface (voice-to-text via Apple)
- **Daily briefing** — proactive Telegram message with today's summary
- **Weekly review** — AI-generated summary of the week's captures and patterns
- **Vector memory** — semantic search over compact memory events using pgvector (deferred
  beyond the Phase 15b foundation)

---

## Why start simple

The first implementation does one thing: take a Telegram text message, classify it with
OpenAI, and show it in a pending inbox. That is the Phase 4–6 milestone.

Every subsequent phase adds one thing:
- Phase 6: the classification actually works end-to-end
- Phase 7: the user can confirm/reject from the dashboard
- Phase 8: confirmed tasks go to a tasks table and tasks view
- Phase 9: confirmed expenses go to a money_events table

Starting simple means:
- The pipeline is proven before the modules are built
- Each module is independently testable
- Bugs are isolated and diagnosable
- The user sees value after Phase 5 without waiting for everything to be built
