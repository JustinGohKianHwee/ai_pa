# AI Personal Assistant

A private, modular AI personal assistant and personal operating system — built to capture,
classify, review, and act on life data across multiple domains.

---

## Long-term vision

A system that feels like a trusted personal memory layer and life command center. You speak
or type naturally through Telegram (or eventually voice notes, email, or a dashboard form),
and the assistant understands what you meant, classifies it, extracts structured data,
stores it in the right place, and surfaces it back to you for review.

Over time, it covers:

- Tasks and reminders
- Personal finance tracking
- Food / calorie / protein logging
- Notes and journal entries
- Calendar and scheduling
- Investment notes
- Daily planning and weekly review
- Goals, habits, and routines
- Eventually: email, documents, life admin

---

## Core architecture principle

**The assistant never takes final action without your review.**

Every capture goes through this pipeline before becoming a permanent record:

```
capture → classify/extract → pending inbox → review → confirm → domain record
```

The review inbox is not a temporary MVP shortcut — it is a permanent, first-class part of
the product. You are always in control of what gets stored and acted on.

---

## Build milestones

**First end-to-end milestone (Phases 4–6):**
> I send a Telegram text message → it appears in the dashboard inbox as a classified
> pending item.

Proves the core pipeline exists. No confirmation, no domain records yet.

**MVP release (Phases 4–8):**
> I capture a task via Telegram → review and confirm it → it appears in my tasks view.

The first usable review-first assistant slice. Everything else — finance, food, calendar,
voice — is built on top of this foundation.

---

## Security note

All non-webhook backend routes require a valid Supabase access token whose subject matches
the configured single owner. The Telegram webhook remains machine-to-machine and validates
its own secret. RLS denies direct anon/authenticated access while the backend retains its
service-role database client.
`SUPABASE_SERVICE_ROLE_KEY` is server-side only and must never reach the frontend or be committed.

---

## Current status

**Phase 14.5 — normalized portfolio snapshots (implementation complete; migration/manual verification pending).**

`GET /portfolio` aggregates current positions, cash, and today's performance across Tiger and
Interactive Brokers, **read-only**. Brokers are fetched independently and concurrently with
bounded per-broker timeouts, so one failing broker never hides the other. IBKR uses the Client
Portal Web API (GET-only allowlist, strict local-TLS); Tiger uses the official `tigeropen` SDK
(lazy-imported, read-method allowlist). Totals are grouped per currency and never summed across
currencies, with per-metric completeness flags. No Supabase access, no broker writes, no
migration. The `/portfolio` dashboard page shows positions, cash, totals, and per-broker status.
Phase 14.5 adds one atomic, normalized portfolio observation per owner/local day, with
per-currency totals and atomic holding/cash rows. It is manually triggered and idempotent;
there is no FX, vector memory, or scheduler. 365 backend tests pass.

Phase 13 (✓ complete): daily review — `GET /daily_review`. Phase 12 (✓ complete): calendar
intents. Phase 11 (✓ complete): food logs. Phase 10 (✓ complete): voice transcription via Whisper.
Migrations `0008` and `0009` require manual application if not already applied.

Milestones: **Phase 6** — classification end-to-end. **Phase 7** — review layer. **Phase 8** —
MVP (tasks + atomic confirm). **Phase 9** — finance expenses. **Phase 10** — voice transcription.
**Phase 11** — food logs. **Phase 12** — calendar intents. **Phase 13** — daily review.
**Phase 14** — read-only portfolio. **Phase 14.5** — normalized snapshots.
**Phase 15a** — authentication + RLS.

---

## How to run locally

### Prerequisites

- Node.js 18.18+ and npm
- Python 3.11+

### Frontend

```bash
cd apps/web
npm install        # already done after Phase 1 scaffold

# Copy env template and fill in the values
# Create apps/web/.env.local with:
#   NEXT_PUBLIC_API_URL=http://localhost:8000
#   NEXT_PUBLIC_SUPABASE_URL=<project URL>
#   NEXT_PUBLIC_SUPABASE_ANON_KEY=<public anon key>

npm run dev        # http://localhost:3000
```

Open http://localhost:3000/inbox to see the dashboard inbox.

### Backend

```bash
cd services/api

# First time only: create the virtual environment and install deps
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # Windows
# source .venv/bin/activate && pip install -r requirements.txt  # macOS/Linux

# Copy env template and fill in the values needed by protected database routes
cp ../../.env.example .env.local   # then edit .env.local
# Set OWNER_USER_ID; SUPABASE_URL also identifies the project's public JWKS endpoint.

# Start the server
.venv/Scripts/uvicorn app.main:app --reload     # Windows
# .venv/bin/uvicorn app.main:app --reload       # macOS/Linux
# → http://localhost:8000
# → http://localhost:8000/docs  (Swagger UI)
# → http://localhost:8000/health
```

### Backend tests

```bash
cd services/api
.venv/Scripts/pytest          # Windows
# .venv/bin/pytest            # macOS/Linux
```

Expected output: all tests pass, covering auth, health, Supabase client, inbox read/review/edit,
task + finance + food + calendar confirmation, the tasks, finance, food, calendar, and daily
review APIs, AI classification, Telegram webhook text capture, and voice transcription. All
external calls are mocked.

---

## Database / migrations

The schema lives in `supabase/migrations/`. `0001_capture_pipeline.sql` creates
`capture_events`, `inbox_items`, and `agent_runs`. `0002_tasks.sql` (Phase 8) adds the
`tasks` table and the `confirm_task_item` atomic-confirmation RPC. `0003_money_events.sql`
(Phase 9) adds the `money_events` table and the `confirm_finance_item` RPC.
`0004_capture_transcription_status.sql` (Phase 10) widens the `processing_status` CHECK
to include `transcription_failed`. `0005_capture_unique_source.sql` (Phase 10) adds
`UNIQUE (source, source_message_id)` on `capture_events` and `UNIQUE (capture_event_id)` on
`inbox_items`. `0006_food_logs.sql` (Phase 11) adds the `food_logs` table and the
`confirm_food_item` atomic-confirmation RPC. `0007_calendar_intents.sql` (Phase 12) adds the
`calendar_intents` table and the `confirm_calendar_item` atomic-confirmation RPC.
`0008_rls_lockdown.sql` (Phase 15a) enables deny-by-default RLS and restricts confirmation
RPC execution to `service_role`. `0009_portfolio_snapshots.sql` (Phase 14.5) adds the three
normalized snapshot tables and atomic `create_portfolio_snapshot` RPC. Apply
migrations in order.

### Apply it (no install required)

1. Create a free project at [supabase.com](https://supabase.com).
2. In the project, open the **SQL Editor**.
3. Paste the entire contents of `supabase/migrations/0001_capture_pipeline.sql` and run it.
4. Verify in the **Table Editor** that all three tables exist, then insert a test row
   into each to confirm the schema works.
5. Copy the project **URL** and keys into `services/api/.env.local`:
   - `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`
   - The service role key is **server-side only** — never put it in frontend code or commit it.

### Alternative: Supabase CLI (optional, needs install)

If you later install the [Supabase CLI](https://supabase.com/docs/guides/cli), you can
apply migrations from the terminal instead of pasting SQL:

```bash
supabase link --project-ref <your-project-ref>
supabase db push        # applies supabase/migrations/*.sql to the linked project
```

> Apply migrations through `0008` before Phase 14.5. Migration `0009` requires manual
> application before using snapshot endpoints. New environments must apply every migration
> in order.

### Phase 15a manual Supabase setup

1. Create the owner under **Authentication → Users** (or sign up once), then disable public
   sign-ups. Disable email confirmation for this private tool, or manually confirm the owner.
2. Copy the owner's UID to backend `OWNER_USER_ID`. The backend derives Supabase's public
   ES256 JWKS endpoint from its existing `SUPABASE_URL`; no signing secret is copied.
3. Copy the project URL and anon key to frontend `NEXT_PUBLIC_SUPABASE_URL` and
   `NEXT_PUBLIC_SUPABASE_ANON_KEY`.
4. Apply `supabase/migrations/0008_rls_lockdown.sql` in the SQL Editor.

Create the owner before disabling sign-ups. Never place the service-role key in
`apps/web/.env.local`; only the project URL and anon key are public-safe.

---

## Repo structure

```
ai_pa/
├── apps/
│   └── web/              # Next.js 15 frontend dashboard (Phase 1+)
├── services/
│   └── api/              # FastAPI Python backend (Phase 1+)
├── docs/                 # Product and architecture documentation
│   ├── product.md        # Vision, principles, domains
│   ├── architecture.md   # System layers and data flow
│   ├── data-model.md     # Conceptual database entities
│   ├── agent-workflow.md # How Claude Code and Codex should work together
│   ├── roadmap.md        # Phase-by-phase build plan
│   ├── mvp-boundary.md   # What is in / out of MVP
│   └── reference-assets.md # Notes on the reference PDFs
├── scripts/              # Utility scripts (Phase 2+)
├── supabase/             # Supabase migrations (Phase 2+)
├── CLAUDE.md             # Durable instructions for Claude Code
├── AGENTS.md             # Durable instructions for Codex
├── .env.example          # Environment variable template
└── README.md             # This file
```

---

## How to use this repo

### Reading order before Phase 1
1. `docs/product.md` — understand the vision and principles
2. `docs/architecture.md` — understand the system layers
3. `docs/data-model.md` — understand the data entities
4. `docs/roadmap.md` — understand what gets built and when
5. `docs/mvp-boundary.md` — understand what is explicitly out of scope

### Agent workflow
- **Claude Code** handles architecture decisions, multi-file implementations, and phase planning
- **Codex** handles focused implementation, code review after Claude phases, and bug fixes
- One phase at a time. Never implement Phase N+1 while Phase N is in progress.
- See `docs/agent-workflow.md` for the full protocol
- See `CLAUDE.md` for Claude Code's standing instructions
- See `AGENTS.md` for Codex's standing instructions

---

## Technology decisions

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Frontend | Next.js 15 + TypeScript + Tailwind | App Router, server components, Vercel-native |
| Backend | FastAPI + Python | Clean async API, great AI SDK support |
| Database | Supabase Postgres | Managed Postgres with Phase 15a RLS lockdown |
| AI (classification) | OpenAI (`gpt-4o-mini`) | Approved Phase 6 structured classifier |
| AI (transcription) | OpenAI Whisper | Best voice-to-text, cheap per minute |
| Capture | Telegram bot | Works on any phone, free, webhook-based |
| Frontend deploy | Vercel | Free tier, native Next.js |
| Backend deploy | Render / Railway / Fly | Simple Python hosting |
