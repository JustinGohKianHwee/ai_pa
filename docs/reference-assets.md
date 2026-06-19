# Reference Assets

Notes on the two reference PDFs provided at project start. These assets are **inspiration,
not a specification.** Do not blindly copy them. Use them to understand the intended
direction, then make deliberate decisions about what fits this implementation.

---

## Assets in this project

| File | Size | Status |
|------|------|--------|
| Community Asset 1.pdf | 2.16 MB | Present but UNREADABLE |
| Community Asset 2.pdf | 47.9 KB | Fully read |

---

## Community Asset 1.pdf

**Status:** Present in the project folder. Could not be read in Phase 0 because the
`pdftoppm` tool required for large PDF rendering is not installed on this machine.

**Impact on Phase 0:** None. All Phase 0 documentation was written based on:
1. The user's fully stated product vision (provided in the Phase 0 prompt)
2. Community Asset 2.pdf (fully readable)

Phase 0 documentation does not depend on or assume any content from Asset 1.

**What to do:** The user can open Asset 1 manually and add relevant notes to this file
before Phase 1 begins, if the asset contains product direction not covered by the stated
vision or Asset 2. If Asset 1 is not reviewed before Phase 1, that is acceptable —
Phase 1 has no dependency on its content.

**Reminder:** These assets are inspiration, not specification. Even if Asset 1 contains
a different architecture or feature set, this implementation follows the review-first
architecture described in `docs/product.md` and `docs/architecture.md`.

---

## Community Asset 2.pdf — "Personal OS Build Cheat Sheet"

**By:** Miles Deutscher / AI Edge

**What it is:** A step-by-step build guide for a personal AI operating system. Covers
stack selection, database schema, Telegram capture pipeline, seven dashboard cards,
a memory/brain layer, deployment, and common bugs. Includes copy-paste prompt blocks
for each step.

---

### Ideas useful now

These patterns from the asset align with or directly inform our architecture:

**Capture pipeline flow:**
> `voice → Telegram bot → Whisper transcription → Claude classifier → database`

This matches our planned pipeline exactly. The asset validates that this approach is
buildable in a reasonable timeframe.

**Table naming conventions (adapted for our model):**
The asset uses `raw_captures`, `tasks`, `daily_logs`, `memory_chunks`, `audit_log`.
We have adapted these into our own model: `capture_events`, `inbox_items`, `agent_runs`,
domain tables per module. The naming is different but the conceptual layer structure is
similar.

**Production gotchas (valuable to know before Phase 16):**
- Use the user's local clock for daily resets, not UTC. Write a `localDateKey()` helper
  that uses the browser/client clock. Server-side UTC causes habits and daily records to
  reset at the wrong time for non-UTC users.
- Page loads must never trigger AI calls. Read from the database; only new captures
  trigger AI. Otherwise API costs compound with every dashboard refresh.
- Telegram voice notes are OGG format. Pass the correct MIME type (`audio/ogg`) to
  Whisper — the wrong content-type causes silent failures.
- Always validate AI-returned IDs exist before writing. Claude can hallucinate entity IDs
  that do not exist in your database. Always check before inserting FKs.
- The `node-ical` library has a BigInt bundler issue on Vercel. Use `ical.js` instead
  for iCal parsing (relevant when calendar sync is added in Phase 12+).
- PostgREST edge cache can serve stale Supabase reads. Add a unique limit parameter
  per request to bust the cache if needed.

**Env var checklist (from Appendix B):**
The asset provides a complete list of env vars needed for the full build. Adapted version
is in `.env.example`. The full list (including vars we will not need until later phases):
`ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `OPENAI_API_KEY`, `TELEGRAM_BOT_TOKEN`,
`TELEGRAM_WEBHOOK_SECRET`, `TELEGRAM_USER_ID`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`,
`SUPABASE_SERVICE_ROLE_KEY`, `USER_TIMEZONE`, `USER_ID`

**Timezone env var:**
The asset uses a `USER_TIMEZONE` env var (e.g. `Asia/Singapore`) for all daily rollover
logic. Add this to `.env.example` when building Phase 10+.

---

### Ideas deferred to future phases

These are valid ideas from the asset but not relevant until a specific later phase:

| Idea | Asset reference | Our phase |
|------|----------------|-----------|
| Habit tracker card | Part 5.3 | Phase 13+ (habits module) |
| Goals card | Part 5.7 | Phase 13+ (goals module) |
| Finance Pulse via Google Sheets | Part 5.8 | Phase 9+ (but Google Sheets integration is later) |
| Calendar card via iCal | Part 5.2 | Phase 12+ |
| CRM / tasks card with Kanban view | Part 5.4 | Phase 8 (simplified), Kanban view is later |
| Nutrition / macros AI estimation | Part 5.5 | Phase 11+ |
| Vector memory (pgvector) | Part 6 | Phase 15+ |
| "Ask my OS" semantic search | Part 6 | Phase 15+ |
| Auth gate (HMAC-signed cookies) | Part 3 | Phase 15 (we use Supabase Auth, not cookie gate) |
| Vercel cron jobs | Part 7 | Phase 16+ |
| Morning briefing via Telegram | Part 9 | Phase 13+ |
| Demo mode toggle | Appendix A17 | Future (not planned yet) |
| Backup export endpoint | Part 7, Step 5 | Phase 16+ |

---

### Ideas we intentionally diverge from

These are places where our architecture makes different choices than the asset. The
divergences are deliberate.

**1. The review layer**

The asset routes captures directly to domain tables:
```
capture → classify → domain table
```

Our architecture inserts a review gate:
```
capture → classify → pending inbox → user review → confirm → domain table
```

The asset's approach is faster to build but bypasses user oversight. For a personal
assistant that handles financial data, health data, and scheduled events, we believe the
review layer is essential. It also means the assistant never "decides" for you.

**2. Separate FastAPI backend**

The asset uses Next.js API routes for all backend logic (Part 3, Part 4). We use a
separate FastAPI Python service.

Reasons:
- FastAPI has better support for long-running tasks (audio transcription, AI calls)
- Python has cleaner async patterns for external API calls
- Separating the backend means the frontend can be deployed to Vercel without worrying
  about Vercel's function timeout limits for AI calls
- Python AI SDKs (Anthropic, OpenAI) are mature and well-documented

Trade-off: slightly more complex local development (run two servers instead of one).
This is acceptable.

**3. Phase ordering**

The asset suggests building all seven dashboard cards (tasks, calendar, habits, nutrition,
goals, finance) roughly in parallel (Parts 5.1–5.8). We build one module per phase.

Our reasoning: each module adds a new database table, new API routes, and new frontend
views. Building them in parallel means if one module has a design problem, it blocks
everything. Building sequentially means each module is independently testable before the
next is started.

**4. Auth approach**

The asset uses a single-password auth gate with HMAC-signed cookies (Part 3, Step 4).
We use Supabase Auth (Phase 15). Supabase Auth is more standard, integrates naturally
with RLS policies, and supports future multi-user expansion if needed.

---

### Important reminder

Neither reference asset should be treated as a final specification. Use them to:
- Validate that the general approach is buildable
- Learn from production gotchas before encountering them
- Find inspiration for UI patterns and UX flows

Always bring ideas from the assets through the lens of our review-first architecture and
phase discipline. If an idea from the asset would bypass the review layer, we do not use it.
