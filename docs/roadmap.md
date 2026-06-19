# Roadmap

Phase-by-phase build plan. Each phase has a single goal, a definition of done, and an
explicit list of what must NOT be built yet.

The rule: complete one phase fully before starting the next. Never work on two phases
simultaneously.

---

## Phase 0 — Repo foundation and product documentation

**Goal:** Establish shared understanding of the product vision, architecture, and build
discipline before writing any application code.

**What gets built:**
- Monorepo folder structure (`apps/web`, `services/api`, `docs`, `scripts`, `supabase`)
- Product documentation (`docs/product.md`, `docs/architecture.md`, `docs/data-model.md`,
  `docs/agent-workflow.md`, `docs/roadmap.md`, `docs/mvp-boundary.md`, `docs/reference-assets.md`)
- Agent instruction files (`CLAUDE.md`, `AGENTS.md`)
- Project README and `.env.example`

**What must NOT be built yet:**
- Any application code (TypeScript, Python, SQL)
- Any `package.json`, `requirements.txt`, or dependency files
- Database schema or migrations
- Telegram bot or AI integration

**Definition of done:**
- All documentation files exist and are complete
- `CLAUDE.md` and `AGENTS.md` contain durable, actionable agent instructions
- Reading the docs gives a new developer (or agent) enough context to start Phase 1
- The user has read `docs/product.md` and `docs/architecture.md`

---

## Phase 1 — Scaffold frontend, backend, and Supabase

**Goal:** Create the empty shells for all three system components. Nothing works end-to-end
yet, but the structure is in place.

**What gets built:**
- `apps/web`: Next.js 15 project, TypeScript strict, Tailwind CSS, App Router
  - Empty home page (placeholder only)
  - No data fetching yet
- `services/api`: FastAPI Python project
  - `main.py` with app definition
  - `GET /health` endpoint that returns `{ status: ok }`
  - Supabase client initialisation (reads env vars, not hardcoded)
- Supabase project created (manual step — user creates via dashboard)
- `.env.local` populated with Supabase URL, anon key, service role key

**What must NOT be built yet:**
- Database migrations or tables
- Telegram bot
- AI calls
- Any real frontend pages or components
- Authentication

**Definition of done:**
- `npm run dev` in `apps/web` shows a blank Next.js page
- `uvicorn main:app` in `services/api` starts FastAPI
- `GET /health` returns 200
- Both apps read from `.env.local` without errors

---

## Phase 2 — Database schema

**Goal:** Create the core Supabase tables needed for the capture pipeline.

**What gets built:**
- `supabase/migrations/0001_capture_pipeline.sql`:
  - `capture_events` table
  - `inbox_items` table (includes `item_type`, `review_status`, optional
    `processing_status`, `reviewed_at`, `confirmed_at`, and `rejected_at` for lightweight
    review audit — no separate `audit_log` table is created)
  - `agent_runs` table
- Migration applied to the Supabase project
- Schema documented and confirmed against `docs/data-model.md`

**What must NOT be built yet:**
- Domain tables (tasks, money_events, etc.) — these come later per module
- `audit_log` or `inbox_review_events` table — deferred future work
- RLS policies — deferred to Phase 15
- Vector / pgvector extension — deferred to Phase 15
- Any indexes beyond primary keys

**Definition of done:**
- All three tables exist in Supabase
- Schema matches the conceptual model in `docs/data-model.md`
- A test row can be inserted into each table manually via Supabase dashboard

---

## Phase 3 — Backend skeleton

**Goal:** Build the FastAPI structure that will power the capture pipeline.

**What gets built:**
- `services/api/routers/` structure
- Supabase client wrapper (`lib/supabase.py`)
- `POST /capture/text` — accepts `{ text, source }`, writes a `capture_events` row,
  returns the created row (no AI yet — `item_type` is the stub `unknown`)
- `GET /inbox` — returns reviewable `inbox_items` where `review_status` is `pending` or
  `needs_manual_classification`

**What must NOT be built yet:**
- Telegram webhook integration
- AI classification calls
- Confirmation / domain record writes

**Definition of done:**
- `POST /capture/text` with `{ "text": "test message", "source": "web_form" }` creates
  a `capture_events` row in Supabase
- `GET /inbox` returns an empty array (or existing rows)
- Manual test via curl or httpie passes

---

## Phase 4 — Telegram text capture

**Goal:** Receive a Telegram text message and store it as a `capture_event`.

**What gets built:**
- Telegram bot created via BotFather (manual step)
- `POST /telegram/webhook` endpoint in FastAPI
  - Verifies `X-Telegram-Bot-Api-Secret-Token` header
  - Verifies message is from the authorised `TELEGRAM_USER_ID`
  - Extracts text from the message
  - Calls the same capture logic as `POST /capture/text`
  - Returns 200 to Telegram immediately
- Webhook registered with Telegram (requires a public URL — use ngrok locally)
- `inbox_items` row created with `review_status = pending`, `item_type = unknown`, and
  `processing_status = received`
  (AI classification is still a stub in this phase)
- `DEV_ADMIN_TOKEN` guard on all non-webhook routes (simple Bearer token check in a
  FastAPI middleware/dependency — development only, replaced by real auth in Phase 15)

**What must NOT be built yet:**
- Voice note transcription
- Real AI classification (stub is fine)
- Any dashboard changes
- Tunneling exposes routes publicly but does not bypass middleware or token checks.
  Prefer path-only exposure for `/telegram/webhook` when supported. If the full backend
  is tunneled, every non-webhook route that reads or mutates personal data must still
  require `DEV_ADMIN_TOKEN`; the webhook validates its own Telegram secret.

**Definition of done:**
- Sending a text message to the Telegram bot creates a row in `capture_events`
- A corresponding `inbox_items` row is created with `review_status = pending`
- The Telegram bot sends a confirmation reply

---

## Phase 5 — Dashboard inbox

**Goal:** The dashboard shows a list of pending inbox items.

**What gets built:**
- `apps/web`: home page `/` shows `inbox_items` where `review_status` is `pending` or
  `needs_manual_classification`
- Each item shows: raw text, item type (stub: "unknown"), processing status, created_at
- Basic Tailwind styling — readable but not polished
- Frontend fetches from `GET /inbox` on the FastAPI backend, sending the
  `DEV_ADMIN_TOKEN` as an `Authorization: Bearer` header (read from local env)

**What must NOT be built yet:**
- Confirm / reject buttons (Phase 7)
- Real classification display (Phase 6)
- Any domain module views

**Definition of done:**
- A Telegram message sent in Phase 4 is visible in the dashboard inbox
- The end-to-end loop works: Telegram → `capture_events` → `inbox_items` → dashboard
- This completes the **first end-to-end milestone**

---

## Phase 6 — AI classification

**Goal:** Claude classifies each capture and populates `extracted_data` on the inbox item.

**What gets built:**
- `services/api/lib/classifier.py` — sends raw text to Claude, returns an item type
  and extracted fields as structured JSON
- Classification is called immediately when a capture is received (after storing the
  `capture_event` but before returning the Telegram confirmation)
- `inbox_items` rows now have a real `item_type`, `extracted_data`, and processing status
- `agent_runs` rows are written for every AI call

**What must NOT be built yet:**
- Voice transcription
- Confirmation / domain record writes
- Any domain module tables

**Definition of done:**
- "Spent $12 on lunch" → inbox item with `item_type = finance`,
  `extracted_data = { amount: 12, currency: SGD, direction: expense, merchant: null, category: food }`
- "Call mum this weekend" → `item_type = task`, `extracted_data = { title: "Call mum", urgency: this_week }`
- `agent_runs` row created for each classification call
- AI confidence and item type visible in the dashboard inbox
- Classification failure or invalid structured output preserves the `capture_event` and
  creates an inbox_item with `item_type = unknown`,
  `review_status = needs_manual_classification`, and the appropriate failure
  `processing_status`; the item remains visible in the dashboard inbox

---

## Phase 7 — Review actions

**Goal:** The user can confirm or reject an inbox item from the dashboard.

**What gets built:**
- Dashboard: Confirm and Reject buttons on each inbox item
- `PATCH /inbox/:id/confirm` — validates `review_status = pending`, `item_type`, and
  `extracted_data`, then atomically sets `review_status = confirmed` and records
  `reviewed_at`. It does **not** write a domain record because no domain tables exist yet.
- `PATCH /inbox/:id/reject` — atomically sets `review_status = rejected` and records `reviewed_at`
- Basic inline edit for `extracted_data` fields before confirming
- Manual classification flow: a `needs_manual_classification` item must receive a valid
  item type and structured data and return to `review_status = pending` before confirmation
- Confirmed and rejected items are removed from the review inbox

**What must NOT be built yet:**
- Domain-specific views (tasks list, finance view)
- Any modules beyond the pipeline
- Domain record writes (no domain tables exist until Phase 8)

**Definition of done:**
- Confirming a task-type inbox item marks it confirmed and records `reviewed_at`. No task record is created
  yet — the tasks table does not exist until Phase 8.
- A `needs_manual_classification` item cannot be confirmed until manually corrected and returned to pending.
- Rejecting any reviewable item marks it rejected and removes it from the review inbox.
- Inline editing of `extracted_data` fields before confirming works and is saved.
- The confirm mechanism is idempotent — confirming an already-confirmed item is a no-op.
- The reject mechanism is idempotent — rejecting an already-rejected item is a no-op.

---

## Phase 8 — Tasks module

**Goal:** Confirmed tasks have a dedicated view and basic management.

**What gets built:**
- Phase 8 **extends** the confirmation mechanism from Phase 7. After Phase 8,
  confirming a pending task-type inbox_item validates its data, creates exactly one linked
  `tasks` row, marks the inbox_item confirmed, and records `reviewed_at` in one atomic
  transaction. A unique `inbox_item_id` prevents duplicate task records.
- `tasks` table migration
- Dashboard `/tasks` page: list of open tasks, grouped by urgency
- `GET /tasks?status=open`, `PATCH /tasks/:id` (mark complete), `DELETE /tasks/:id`
- Basic task display: title, urgency, due date, created at

**What must NOT be built yet:**
- Task editing from tasks view (edit happens in the inbox before confirmation)
- Sub-tasks
- Priority scoring or AI ranking
- Any other domain module

**Definition of done:**
- A task confirmed after the Phase 8 task module exists appears in the tasks view
- Items confirmed before Phase 8 remain confirmed inbox_items only; retroactive backfill
  is optional future/admin work and is not required for this phase
- Tasks can be marked complete
- Tasks are grouped by urgency tier
- This completes the **MVP release**

---

## Phase 9 — Finance module

**Goal:** Confirmed expenses appear in a finance view.

**What gets built:**
- `money_events` table migration
- Dashboard `/finance` page: list of recent expenses
- `GET /money_events`, basic total by category
- Expense display: amount, currency, merchant, category, date

**What must NOT be built yet:**
- Income tracking
- Net worth calculation
- Google Sheets integration
- Charts or aggregations beyond simple totals

**Definition of done:**
- A finance item confirmed after the Phase 9 finance module exists appears in the finance view
- Expenses are grouped or sorted by date
- Basic total by category is shown

---

## Phase 10 — Voice transcription

**Goal:** Telegram voice notes are transcribed and processed through the same pipeline.

**What gets built:**
- Telegram webhook handler extended to detect voice messages
- Audio download from Telegram servers
- OpenAI Whisper transcription call
- Transcribed text passed to the same classifier used for text
- `capture_events.audio_url` populated with the stored audio file

**Note on audio format:** Telegram voice notes are OGG format. Pass the correct MIME
type (`audio/ogg`) to Whisper.

**What must NOT be built yet:**
- Audio playback in the dashboard
- Any changes to domain modules

**Definition of done:**
- Sending a voice note to the Telegram bot creates the same pipeline as text
- The transcription appears as the `raw_text` on the `capture_event`
- The inbox item shows the transcript

---

## Phase 11 — Food logs module

**Goal:** Confirmed food entries have a dedicated view.

**What gets built:**
- `food_logs` table migration
- Dashboard `/food` page: today's meals
- `GET /food_logs?date=today`
- Basic display: description, meal type, time, optional calorie estimate

**Definition of done:**
- "Ate chicken rice for lunch" → confirmed inbox item → food log entry → visible in food view

---

## Phase 12 — Calendar intents module

**Goal:** Confirmed calendar intentions are stored and visible.

**What gets built:**
- `calendar_intents` table migration
- Dashboard `/calendar` page: upcoming calendar intents
- `GET /calendar_intents`
- Basic display: title, proposed datetime, location

**Note:** This is NOT live calendar sync. `calendar_intents` are records of intention.
Syncing to Google Calendar / Apple Calendar is a later phase requiring OAuth and conflict
detection.

**Definition of done:**
- "Dinner with Zoey next Friday 7pm at Jewel" → confirmed inbox item → calendar intent → visible in calendar view

---

## Phase 13 — Daily review

**Goal:** A daily review view that surfaces what was captured and confirmed today.

**What gets built:**
- Dashboard `/review` page: today's captures, confirmed items by domain, rejected items
- A summary generated by Claude: "Today you captured N items, confirmed X tasks, Y expenses"
- Basic AI-generated reflection prompt (optional)

**What must NOT be built yet:**
- Weekly review
- Historical aggregations
- Habit tracking

**Definition of done:**
- The review page shows today's activity across all active domains

---

## Phase 14 — Investments module

**Goal:** Confirmed investment notes are stored and visible.

**What gets built:**
- `investment_notes` table migration
- Dashboard `/investments` page: investment notes list
- `GET /investment_notes`
- Basic display: ticker, action intent, amount, date, notes

**Definition of done:**
- "Buy $350 CSPX this month" → confirmed inbox item → investment note → visible in investments view

---

## Phase 15 — Auth, RLS, and vector memory

**Goal:** Secure the system and add semantic memory search.

**What gets built:**
- Supabase Auth integration
- RLS policies on all tables (service role bypasses, anon/user role is restricted)
- `memory_chunks` table with pgvector extension
- Embeddings written for every confirmed domain record
- `POST /memory/search` — semantic search endpoint
- Dashboard search bar that queries memory

**Note on vector memory:** Standard SQL queries cover most use cases. Add this when you
need to ask questions across months of data, not days.

**Definition of done:**
- All routes require authentication
- "What did I spend money on last week?" returns relevant money_events via semantic search

---

## Phase 16 — Deployment

**Goal:** The system runs in production, accessible from anywhere.

**What gets built:**
- Frontend deployed to Vercel
  - Environment variables configured
  - Custom domain (optional)
- Backend deployed to Render / Railway / Fly
  - Environment variables configured
  - Telegram webhook re-registered to production URL
- Production Supabase project (or promote dev project)
- Monitoring and basic error alerting

**Definition of done:**
- Sending a Telegram message from a phone creates an inbox item visible at the production URL
- The system handles a full day of real use without errors
