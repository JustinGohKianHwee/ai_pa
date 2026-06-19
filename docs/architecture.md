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
  - validate inbox_item item_type, extracted_data, and review_status
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
- Telegram bot — text messages and voice notes (Phase 4+)
- Dashboard web form — typed input (Phase 5+)
- Voice notes via Telegram (Phase 10+)
- Future: email, iOS Shortcuts, documents

**What happens here:**
- The raw input arrives at a backend webhook endpoint
- It is written immediately to `capture_events` as an immutable record
- If the input is a voice note, it is passed to the transcription layer
- The raw text is then passed to the classification layer
- The capture_event is never modified after this point

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

**Deferred until:** Phase 10. Text-only capture is sufficient for Phases 4–9.

---

## Layer 3: AI Classification and Extraction

**What it is:** The AI brain that interprets natural language and extracts structured data.

**Technology:** Claude (Anthropic) — primary. OpenAI — fallback.

**What happens here:**
- The raw text is sent to Claude with a structured system prompt
- Claude returns a JSON object containing:
  - `item_type`: what kind of item this is (task / finance / calendar / food / investment / note / journal / unknown)
  - `extracted_data`: structured fields relevant to that type (amount, date, merchant, due_date, urgency, etc.)
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

If Claude returns an error, times out, or returns invalid structured output:
- The `capture_event` already exists and is unaffected
- An `inbox_item` is created with `item_type = "unknown"`,
  `review_status = "needs_manual_classification"`, and `processing_status` set to
  `classification_failed` or `invalid_ai_output`
- `extracted_data` is set to `{}`; safe error metadata may be retained separately
- An `agent_runs` row is written with the error detail
- The item appears in the dashboard review inbox
- The user must manually choose a valid `item_type` and provide valid structured data;
  the item then returns to `review_status = "pending"` before it can be confirmed
- No domain record is created

If AI returns structurally valid JSON but with invalid field values (e.g. a date that
does not parse, an amount that is not a number):
- The backend validates `extracted_data` before accepting it
- Invalid fields are stripped or set to `null` rather than rejecting the whole response
- The item is stored with whatever valid data was extracted; `extracted_data` may include
  a `validation_warnings` array noting which fields were dropped
- The user sees the partial data and can correct it manually before confirming

---

## Layer 4: Pending Inbox

**What it is:** The review gate. All classified items live here until the user acts.

**Storage:** `inbox_items` table in Supabase

**What an inbox_item contains:**
- Reference to the original `capture_event`
- `item_type` — `task`, `finance`, `calendar`, `food`, `investment`, `note`, `journal`, or `unknown`
- `extracted_data` — the structured fields the AI extracted (JSONB)
- `ai_confidence` — how confident the AI was
- `review_status` — `pending`, `needs_manual_classification`, `confirmed`, or `rejected`
- Optional `processing_status` — `received`, `classified`, `classification_failed`, or `invalid_ai_output`
- `created_at`, `reviewed_at`, `confirmed_at`, and `rejected_at` timestamps

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
2. The backend validates its `item_type` and `extracted_data`
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
- `investment_notes` — confirmed investment notes (Phase 14+)

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
Every raw capture is immutable and remains the ground-truth input history.

**AI call audit — `agent_runs` (Phase 2+):**
Every AI model call is recorded in `agent_runs`: model, call type, token count, latency,
and a summary of the prompt and result. This is the transparency log for all AI work
done by the system, including classification failures.

**User review audit — inbox_item state and timestamps:**
The `inbox_items` table carries `review_status`, `reviewed_at`, `confirmed_at`, and
`rejected_at`. These provide a lightweight record of the user's review decision.
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
- Investments view (Phase 14+)

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

**Development security (Phases 4–15)**

Until Phase 15 (auth/RLS), the following rules apply:

- The backend runs locally by default. No routes are publicly accessible unless a
  tunnel is explicitly started.
- A `DEV_ADMIN_TOKEN` env var must be set during Phases 4–15. All non-webhook API
  routes must check for `Authorization: Bearer <DEV_ADMIN_TOKEN>` before serving any
  request. This is a development guard only — it is replaced by real auth in Phase 15.
- The Telegram webhook path (`/telegram/webhook`) is the only route that should ever
  be exposed publicly. It must validate `X-Telegram-Bot-Api-Secret-Token` before
  accepting any payload.
- Tunneling exposes routes publicly but does not bypass middleware or token checks.
  Prefer path-only exposure for `/telegram/webhook` when the tunnel supports it. If the
  full backend is tunneled, every non-webhook route that reads or mutates personal data
  must still enforce `DEV_ADMIN_TOKEN`.
- `SUPABASE_SERVICE_ROLE_KEY` is used only server-side. It must never appear in
  frontend environment variables, browser bundles, or client-visible responses.
- The Next.js frontend may use `SUPABASE_ANON_KEY` for read-only queries, or call
  the FastAPI backend (which holds the service key) for mutations and protected data.

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
- `investment_notes` (Phase 14+)
- `user_preferences` (Phase 15+)
- `memory_chunks` — vector embeddings (Phase 15+)

**Auth / RLS:** Deferred to Phase 15. During development, the service role key is used
and RLS is not enforced.

---

## Layer 10: Future Integrations

These are not in scope until the core pipeline is working.

- **Google Calendar** — sync confirmed `calendar_intents` to a real calendar event
- **Email capture** — parse emails as capture events
- **iOS Shortcuts** — alternative capture surface (voice-to-text via Apple)
- **Daily briefing** — proactive Telegram message with today's summary
- **Weekly review** — AI-generated summary of the week's captures and patterns
- **Vector memory** — semantic search over past captures using pgvector (Phase 15+)

---

## Why start simple

The first implementation does one thing: take a Telegram text message, classify it with
Claude, and show it in a pending inbox. That is the entire Phase 4–5 loop.

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
