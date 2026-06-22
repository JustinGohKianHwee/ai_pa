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

## Phase 1 — Scaffold frontend, backend, and Supabase ✓ complete

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

## Phase 2 — Database schema (migration ready; Supabase application pending)

**Goal:** Create the core Supabase tables needed for the capture pipeline.

**What gets built:**
- `supabase/migrations/0001_capture_pipeline.sql`:
  - `capture_events` table — includes `processing_status` (`received` /
    `classified` / `classification_failed` / `invalid_ai_output`) and a `metadata`
    JSONB column
  - `inbox_items` table — includes `item_type`, `review_status`, `reviewed_at`,
    `structured_json`, and an auto-maintained `updated_at` (via trigger). Review-state
    audit is `review_status` + `reviewed_at`; there are no separate `confirmed_at` /
    `rejected_at` columns and no separate `audit_log` table
  - `agent_runs` table
- A small set of query indexes (see below)
- Migration applied to the Supabase project
- Schema documented and confirmed against `docs/data-model.md`

**Indexes added this phase:**
- `inbox_items(review_status)`, `inbox_items(item_type)`, `inbox_items(created_at)`
- `capture_events(created_at)`, `agent_runs(created_at)`

These support the dashboard inbox (filter by status/type, order by recency) and
chronological reads of the append-only tables.

**What must NOT be built yet:**
- Domain tables (tasks, money_events, etc.) — these come later per module
- `audit_log` or `inbox_review_events` table — deferred future work
- RLS policies — deferred to Phase 15
- Vector / pgvector extension — deferred to Phase 15
- Indexes beyond the small query set listed above

**Definition of done:**
- All three tables exist in Supabase
- Schema matches the model in `docs/data-model.md`
- A test row can be inserted into each table manually via Supabase dashboard

---

## Phase 3 — Backend skeleton ✓ complete

**Goal:** Establish protected backend-only database connectivity without adding capture or
inbox behavior yet.

**What gets built:**
- Backend-only Supabase client factory using `SUPABASE_URL` and
  `SUPABASE_SERVICE_ROLE_KEY`, created lazily with no import-time queries
- Reusable `development bearer token` dependency for private development routes
- Public `GET /health`, independent of Supabase configuration
- Protected, read-only `GET /health/db` connectivity check
- Unit tests with the Supabase client mocked; no real network calls

**What must NOT be built yet:**
- Capture or inbox CRUD routes
- Telegram webhook integration
- AI classification calls
- Confirmation / domain record writes
- Frontend dashboard behavior
- Auth or RLS

**Definition of done:**
- `GET /health` returns 200 without Supabase credentials or a development token
- `/health/db` rejects missing or invalid development tokens
- With a valid token, `/health/db` performs only a read-only mocked connectivity query in tests
- Missing Supabase settings fail clearly only when a DB-dependent route is used
- The backend test suite passes without real Supabase network access

---

## Phase 4 — Telegram text capture ✓ complete

**Goal:** Receive a Telegram text message and store it as a `capture_event`.

**What gets built:**
- Telegram bot created via BotFather (manual step)
- `POST /telegram/webhook` endpoint in FastAPI
  - Verifies `X-Telegram-Bot-Api-Secret-Token` header
  - Verifies message is from the authorised `TELEGRAM_USER_ID`
  - Extracts text from the message
  - Passes the text to the Phase 4 capture logic
  - Returns 200 to Telegram immediately
- Webhook registered with Telegram (requires a public URL — use ngrok locally)
- `inbox_items` row created with `review_status = pending` and `item_type = unknown`;
  the linked `capture_event` has `processing_status = received`
  (AI classification is still a stub in this phase)
- `development bearer token` guard on all non-webhook routes (simple Bearer token check in a
  FastAPI middleware/dependency — development only, replaced by real auth in Phase 15)

**What must NOT be built yet:**
- Voice note transcription
- Real AI classification (stub is fine)
- Any dashboard changes
- Tunneling exposes routes publicly but does not bypass middleware or token checks.
  Prefer path-only exposure for `/telegram/webhook` when supported. If the full backend
  is tunneled, every non-webhook route that reads or mutates personal data must still
  require `development bearer token`; the webhook validates its own Telegram secret.

**Definition of done:**
- Sending a text message to the Telegram bot creates a row in `capture_events`
- A corresponding `inbox_items` row is created with `review_status = pending`
- The Telegram bot sends a confirmation reply

---

## Phase 5 — Dashboard inbox ✓ complete

**Goal:** The dashboard shows a list of pending inbox items.

**What gets built:**
- `apps/web`: home page `/` shows `inbox_items` where `review_status` is `pending` or
  `needs_manual_classification`
- Each item shows: raw text, item type (stub: "unknown"), processing status, created_at
- Basic Tailwind styling — readable but not polished
- Frontend fetches from `GET /inbox` on the FastAPI backend, sending the
  `development bearer token` as an `Authorization: Bearer` header (read from local env)

**What must NOT be built yet:**
- Confirm / reject buttons (Phase 7)
- Real classification display (Phase 6)
- Any domain module views

**Definition of done:**
- A Telegram message sent in Phase 4 is visible in the dashboard inbox
- The end-to-end loop works: Telegram → `capture_events` → `inbox_items` → dashboard
- This completes the capture-to-dashboard display loop. Phase 6 classification completes
  the **first end-to-end milestone**.

---

## Phase 6 — AI classification ✓ complete

**Goal:** OpenAI (`gpt-4o-mini`) classifies each capture and populates `structured_json`
on the inbox item.

**What gets built:**
- `services/api/app/services/classifier.py` — sends raw text to OpenAI, returns an item type
  and extracted fields as structured JSON
- Classification is called immediately when a capture is received (after storing the
  `capture_event` but before returning the Telegram confirmation)
- `inbox_items` rows now have a real `item_type`, `structured_json`, and confidence;
  processing status is updated on the linked `capture_event`
- `agent_runs` rows are written for every AI call

**What must NOT be built yet:**
- Voice transcription
- Confirmation / domain record writes
- Any domain module tables

**Definition of done:**
- "Spent $12 on lunch" → inbox item with `item_type = finance`,
  `structured_json = { amount: 12, currency: SGD, direction: expense, merchant: null, category: food }`
- "Call mum this weekend" → `item_type = task`, `structured_json = { title: "Call mum", urgency: this_week }`
- `agent_runs` row created for each classification call
- AI confidence and item type visible in the dashboard inbox
- Classification failure or invalid structured output preserves the `capture_event` and
  creates an inbox_item with `item_type = unknown`,
  `review_status = needs_manual_classification`, while the linked capture_event receives
  the appropriate failure `processing_status`; the item remains visible in the dashboard inbox

---

## Phase 7 — Review actions ✓ complete

**Goal:** The user can confirm or reject an inbox item from the dashboard.

**What gets built:**
- Dashboard: Confirm and Reject buttons on each inbox item
- `PATCH /inbox/:id/confirm` — validates `review_status = pending`, `item_type`, and
  `structured_json`, then atomically sets `review_status = confirmed` and records
  `reviewed_at`. It does **not** write a domain record because no domain tables exist yet.
- `PATCH /inbox/:id/reject` — atomically sets `review_status = rejected` and records `reviewed_at`
- Basic inline edit for `structured_json` fields before confirming
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
- Inline editing of `structured_json` fields before confirming works and is saved.
- The confirm mechanism is idempotent — confirming an already-confirmed item is a no-op.
- The reject mechanism is idempotent — rejecting an already-rejected item is a no-op.

---

## Phase 8 — Tasks module ✓ complete

**Goal:** Confirmed tasks have a dedicated view and basic management.

**What gets built:**
- Phase 8 **extends** the confirmation mechanism from Phase 7. After Phase 8,
  confirming a pending task-type inbox_item validates its data, creates exactly one linked
  `tasks` row, marks the inbox_item confirmed, and records `reviewed_at` in one atomic
  transaction. A unique `inbox_item_id` prevents duplicate task records.
- `tasks` table migration (`supabase/migrations/0002_tasks.sql`) + `confirm_task_item` RPC
- Dashboard `/tasks` page: open tasks grouped by urgency, completed tasks in a separate section
- `GET /tasks`, `PATCH /tasks/{id}/complete` (mark complete)
- Basic task display: title, urgency, due date, notes, created at

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

## Phase 9 — Finance module ✓ complete

**Goal:** Confirmed expenses appear in a finance view.

**What gets built:**
- `money_events` table migration (`supabase/migrations/0003_money_events.sql`) +
  `confirm_finance_item` atomic RPC (mirrors the Phase 8 task pattern)
- Dashboard `/finance` page: recent expenses + totals grouped by currency and category
- `GET /money_events` (read-only; returns items + `totals_by_currency`)
- Expense display: amount, currency, merchant, category, occurred text, notes, date

**Income decision:** income tracking is out of scope. Finance **expense** items confirm
atomically into `money_events`; finance **income** items confirm status-only (Phase 7 path,
no domain record) and are not backfilled when income support later lands. The schema permits
`direction in (expense, income)` but Phase 9 only ever creates expense rows.

**What must NOT be built yet:**
- Income tracking / UI
- Net worth calculation
- Google Sheets integration
- Charts or aggregations beyond simple totals
- Finance editing or deletion after confirmation

**Definition of done:**
- A finance expense confirmed after the Phase 9 module exists appears in the finance view
- Expenses are ordered by `created_at`; totals shown per currency, broken down by category
- Different currencies are never summed together

---

## Phase 10 — Voice transcription ✓ complete

**Manual verification passed:** An English voice note created one `telegram_voice` capture with
`raw_text=null`, a populated transcript, `processing_status="classified"`, one linked inbox
item, and separate transcriber / classifier audit rows. Duplicate replay created no new rows.

**Goal:** Telegram voice notes are transcribed and processed through the same pipeline.

**What gets built:**
- Telegram webhook handler extended to detect voice messages
- Audio download from Telegram servers
- OpenAI Whisper transcription call
- Transcribed text passed to the same classifier used for text
- `capture_events.audio_file_id` populated with the stored audio-file reference

**Note on audio format:** Telegram voice notes are OGG format. Pass the correct MIME
type (`audio/ogg`) to Whisper. Transcription is currently pinned to English (`language="en"`)
to prevent incorrect automatic language detection.

**What must NOT be built yet:**
- Audio playback in the dashboard
- Any changes to domain modules

**Definition of done:**
- Sending a voice note to the Telegram bot creates the same pipeline as text
- The transcription appears in `capture_events.transcript`; raw source fields remain unchanged
- The inbox item shows the transcript

---

## Phase 11 — Food logs module ✓ complete

**Goal:** Confirmed food entries have a dedicated view.

**What gets built:**
- `supabase/migrations/0006_food_logs.sql` — `food_logs` table + `confirm_food_item` atomic RPC
- `GET /food_logs` — read-only list; `?date=today` filter uses `created_at` with
  `USER_TIMEZONE`-aware midnight boundaries (not `logged_at`)
- Dashboard `/food` page: today's meals (server component, force-dynamic)
- `tzdata` added to requirements for cross-platform `zoneinfo` support

**Key decisions (Phase 11):**
- `logged_at` stored as TEXT — verbatim AI output, not parsed, not filterable
- `?date=today` = user's local calendar day of confirmation (`created_at`), not meal time
- No `user_id`, `estimated_calories`, `estimated_protein_g`, or `notes` (Phase 15 / future)
- Invalid `date=` values return 422 (no silent fallback to all-records)

**Definition of done:**
- "Ate chicken rice for lunch" → confirmed inbox item → food log entry → visible in /food
- `GET /food_logs?date=yesterday` → 422

---

## Phase 12 — Calendar intents module ✓ complete

**Goal:** Confirmed calendar intentions are stored and visible.

**What gets built:**
- `supabase/migrations/0007_calendar_intents.sql` — `calendar_intents` table +
  `confirm_calendar_item` atomic RPC (same 9-step pattern as tasks, finance, food)
- `GET /calendar_intents` — all intents ordered by `created_at DESC` (no date filter)
- Dashboard `/calendar` page: confirmed intentions (server component, force-dynamic)

**Key decisions (Phase 12):**
- `proposed_datetime` stored as TEXT — verbatim AI output, not parsed, display only
- No `status` column (`draft`/`synced` deferred until calendar sync is introduced)
- No `user_id` (single-user until Phase 15)
- Display order: `created_at DESC`; page titled "Calendar Intents", not "Upcoming Events"

**Note:** This is NOT live calendar sync. `calendar_intents` are records of intention.
Syncing to Google Calendar / Apple Calendar is a later phase requiring OAuth and conflict
detection.

**Definition of done:**
- "Dinner with Zoey next Friday 7pm at Jewel" → confirmed inbox item → calendar intent → visible in /calendar

---

## Phase 13 — Daily review ✓ complete

**Goal:** A daily review view that surfaces what was captured and reviewed today.

**What gets built:**
- `GET /daily_review?date=today` — read-only endpoint, three queries on existing tables, no migration
- Dashboard `/review` page: today's captures, confirmed items, rejected items, pending items (server component, force-dynamic)
- Deterministic summary string ("5 items captured. 3 confirmed (2 tasks, 1 food log). 1 rejected.")

**Key decisions (Phase 13):**
- "Captured today" = `capture_events.created_at` in today's UTC window (immutable source; avoids partial-failure recovery skew)
- "Confirmed/rejected today" = `inbox_items.reviewed_at` in today's UTC window
- "Pending today" = captured_today items with `review_status IN ('pending', 'needs_manual_classification')` — Python filter, no extra query
- `USER_TIMEZONE` is **required**; missing or invalid → 503 (no silent UTC default)
- Empty state only when all three counts (captured, confirmed, rejected) are zero
- Summary: deterministic — no AI call, no new dependency, no per-refresh cost
- Reflection prompt: deferred

**What must NOT be built yet:**
- Weekly review, historical aggregations, habit tracking
- AI-generated summary (approved deferred)
- Any writes to domain tables

**Definition of done:**
- `GET /daily_review` returns correct counts for today's activity; `/review` page displays them
- Automated verification and manual E2E passed: timezone-aware capture/review counts,
  deterministic summary, rejected-only behavior, pending transitions, and `/review` display
  were confirmed against the local environment

---

## Phase 14 — Read-only portfolio aggregation (implementation complete; manual verification pending)

**Goal:** Show current portfolio positions and today's performance across Tiger Brokers and
Interactive Brokers (IBKR), using broker APIs as the source of truth.

**Status:** Backend (`app/brokers/` adapters + `GET /portfolio`), frontend (`/portfolio`), and
tests are implemented; 317 backend tests pass (all mocked). Live broker connectivity has not yet
been verified against the user's real accounts — see the definition of done.

**What gets built:**
- Backend-only read-only adapters for Tiger and IBKR, behind a small normalized portfolio
  interface
- `GET /portfolio` protected by `development bearer token`
- Dashboard `/portfolio` page showing positions, cash, market value, unrealized P&L, today's
  P&L, broker/account source, currency, quote freshness, and last-updated time when available
- Independent broker health/error reporting so one unavailable broker does not hide data from
  the other
- Totals grouped by currency; currencies are not added together without an explicit FX source

**Key decisions (Phase 14):**
- **IBKR via the Client Portal Web API (CPAPI)** over httpx to a local Client Portal Gateway;
  the adapter is strictly GET-only (allowlisted paths) with strict local-TLS handling.
- **Tiger via the official `tigeropen` SDK**; today's P&L is broker-reported per position
  (`get_positions` carries a `today_pnl` field), with the account-level figure summed from
  those. Fractional-share quantities use Tiger's `position_qty` (the scaled `quantity` field
  is descaled by `position_scale`). Configurable via a `tiger_openapi_config.properties`
  file (`TIGER_PROPS_PATH`) or the explicit id/account/key trio.
- Read-only is enforced in code: per-adapter call allowlists, no generic broker-request method
  exported, no non-GET requests to IBKR. CPAPI sessions inherit the user's full permissions —
  documented residual risk mitigated by the allowlist + GET-only surface.
- Per-broker bounded timeouts with a bounded executor and per-broker single-flight guard so a
  hung broker cannot accumulate background threads across refreshes.
- Currency totals track completeness per metric; an incomplete subtotal is never presented as a
  full total.
- Broker APIs are authoritative for positions. Natural-language captures and confirmed
  `investment` inbox items do not directly modify portfolio positions.
- This phase is read-only: no orders, cancellations, transfers, or brokerage writes.
- Broker credentials and account identifiers remain backend-only and are never returned to the
  browser or written to logs.
- No portfolio table or snapshot migration is introduced in the initial phase. Explicit,
  normalized snapshots are added separately in Phase 14.5 after both live adapters are verified.
- MCP may later expose the normalized read-only portfolio tools, but MCP and trade execution are
  not part of Phase 14.

**What must NOT be built yet:**
- Trade placement, cancellation, modification, or automated execution
- Order previews presented as executable authorization
- Portfolio updates derived from Telegram or AI output
- Market recommendations or investment advice
- Historical performance charts or scheduled snapshots
- Cross-currency totals without an approved FX source
- MCP tools or brokerage write permissions

**Definition of done:**
- Real read-only Tiger and IBKR connections are manually verified against the user's accounts
- `/portfolio` shows normalized positions from both brokers and identifies their source/freshness
- Partial failure is visible and usable: one broker can fail while the other still returns data
- Refreshing the portfolio performs no brokerage or database writes

---

## Phase 14.5 — Daily portfolio snapshots (implementation complete; migration/manual verification pending)

**Goal:** Preserve one normalized Tiger/IBKR portfolio observation per local portfolio day in
Supabase so later SQL analysis and memory generation can use reliable historical data.

**What gets built:**
- Migration `0009_portfolio_snapshots.sql` with snapshot headers, per-currency totals, and
  atomic position/cash rows plus a service-role-only persistence RPC
- A protected manual `POST /portfolio/snapshots` using `USER_TIMEZONE` for the local date
- Idempotency protection so retries or repeated manual requests do not create more
  than one canonical snapshot for the same portfolio day
- Protected list, date-detail, and per-currency history endpoints
- Snapshot-run status and safe broker-level failure metadata so missing/stale broker data is not
  mistaken for a complete portfolio

**Key decisions (Phase 14.5):**
- Broker APIs remain authoritative for current positions. Supabase snapshots are historical
  observations and may be stale.
- Store normalized fields only — never raw broker responses, credentials, session data, private
  keys, or full account numbers.
- Store masked account references and a stable asset id (`instrument_id` or
  `broker:symbol:currency`); never persist a full broker account number.
- Preserve native currency, P&L source (`broker`, `calculated`, `unavailable`), completeness,
  quote status, broker `as_of`, and snapshot timestamps.
- Snapshot persistence is atomic: the run and all associated account/position/cash rows commit
  together or roll back together.
- Phase 14.5 is manually triggered only. Scheduling remains deferred until deployment.
- This explicit external-data snapshot flow is not an inbox confirmation and does not create or
  modify tasks, expenses, food logs, calendar intents, or broker positions.

**What must NOT be built yet:**
- A snapshot on every `/portfolio` page load
- Per-market or intraday high-frequency snapshots
- Historical charts, performance attribution, or FX conversion
- Vector embeddings or generated memory statements
- Brokerage writes, MCP tools, or trade execution

**Definition of done:**
- A manual request creates or refreshes one normalized snapshot for the local portfolio day
- Repeating the request is idempotent for `(owner_id, snapshot_date)`
- Partial or failed persistence leaves no half-written snapshot
- The latest snapshot can be read back without exposing broker secrets or full account numbers
- Broker unavailability is recorded safely and never presented as a complete snapshot
- Refreshing `/portfolio` creates no database rows

---

## Phase 15a — Authentication + RLS (implementation complete; manual setup pending)

**Goal:** Replace the temporary development guard with single-owner authentication and
lock direct database access down without changing the review-first pipeline.

**What gets built:**
- Supabase email/password authentication with cookie-based Next.js sessions
- ES256 access-token verification through Supabase's public JWKS plus `OWNER_USER_ID`
  enforcement on protected FastAPI routes
- Service-role backend access retained behind API-layer authentication
- Deny-by-default RLS and revoked anon/authenticated grants on all current tables and confirm RPCs
- Migration `0008_rls_lockdown.sql`

**Definition of done:**
- Logged-out dashboard requests redirect to `/login`; owner login and logout work
- Protected APIs return 401 without a valid session and 403 for a valid non-owner token
- Anon/authenticated database access is denied while service-role backend access continues
- Telegram capture and review-first confirmation remain unchanged

## Phase 15b — Memory-ready foundation (implementation complete; migration/manual verification pending)

**Goal:** Establish the ownership and event contracts needed by future memory features without
adding embeddings, vector search, or a memory API.

**What gets built:**
- Migration `0010_owner_id.sql` adds a default-filled, non-null `owner_id` to the seven
  pre-snapshot tables. The portfolio snapshot tables already carry `owner_id`.
- Migration `0011_memory_events.sql` creates an append-only, RLS-locked `memory_events` log.
- Task, expense, food, and calendar confirmation RPCs append one compact `confirmed` event in
  the same transaction as the domain record and inbox confirmation.
- The portfolio snapshot RPC replaces its matching `snapshot_created` event when the canonical
  snapshot for an owner/date is refreshed, preserving one event per snapshot.

**Key constraints:**
- The user must replace `<OWNER_USER_ID>` in both migrations before applying them manually.
- Existing confirmation atomicity, idempotency, validation, and review-first behavior are unchanged.
- `daily_summaries`, `embedding_queue`, embeddings, pgvector, memory APIs/UI, and per-user RLS
  policies remain deferred to later phases.

**Definition of done:**
- Every current table has a non-null owner identifier after the migrations are applied.
- A successful domain confirmation commits exactly one corresponding memory event; a failed
  confirmation commits neither the domain change nor a memory event.
- Re-running the same portfolio snapshot keeps one `snapshot_created` event for that snapshot.
- Direct anon/authenticated access to `memory_events` is denied.

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
- Scheduled daily portfolio snapshot (the Phase 14.5 system): a cron at ~07:00 Asia/Singapore
  (after US market close, ~04:00–05:00 SGT) that triggers `POST /portfolio/snapshots`.
  Prerequisites/notes: needs the always-on deployed backend; Tiger can run unattended, but
  IBKR's Client Portal session expires and can't easily run unattended (expect IBKR-partial
  snapshots until a keepalive/re-auth approach is chosen); the scheduled snapshot must label
  `snapshot_date` with the **US trading day**, not the local calendar date.

**Definition of done:**
- Sending a Telegram message from a phone creates an inbox item visible at the production URL
- The system handles a full day of real use without errors
