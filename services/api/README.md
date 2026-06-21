# services/api — Backend API

**Status: Phase 10 — voice transcription ✓ complete.**

Telegram voice notes are now captured and transcribed through the same pipeline as text. The
webhook detects `message.voice`, downloads the OGG via Telegram's `getFile` API (25 MB limit),
transcribes it with OpenAI Whisper (`whisper-1`, pinned to English with `language="en"`), and feeds the transcript to the existing
classifier. Transcription failure sets `processing_status="transcription_failed"` and
`review_status="needs_manual_classification"`. Two `agent_runs` rows are written on the happy
path: `transcriber` then `text_classifier`. 186 tests pass (all mocked).

Phase 9 (✓ complete): Confirming a **task** calls the `confirm_task_item` RPC; confirming a
finance **expense** calls the `confirm_finance_item` RPC — each atomically creates one linked
domain row, marks the item `confirmed`, and records `reviewed_at`. Finance **income** and
module-less types use the Phase 7 status-only path. Migrations `0001`–`0005` are applied to
the project, and the Phase 10 voice-note E2E has passed.

## Planned stack
- Python 3.11+
- FastAPI
- Supabase Python client (server-side only; service role key never exposed to frontend)
- OpenAI Python SDK — Phase 6 classification (`gpt-4o-mini`) and Phase 10 transcription
- Anthropic SDK — not required for Phase 6; reserved for possible future capabilities

## Role in the system
The backend enforces the core pipeline:
**capture → classify/extract → pending inbox → (await review) → confirm → domain record**

1. Receiving Telegram webhook events (Phase 4+)
2. Downloading and transcribing voice notes (Phase 10+)
3. Calling OpenAI to classify and extract structured data (Phase 6+)
4. Writing classified items to Supabase `inbox_items` as pending records
5. Handling review actions from the dashboard — confirm / reject / edit (Phase 7+); atomic
   confirm-plus-domain-record creation begins in Phase 8 (tasks) and Phase 9 (finance expenses)
6. Running AI calls — page loads never trigger AI directly

## Directory layout

```
app/
  main.py            — FastAPI app, registers all routers
  config.py          — env var reads (module-level reference; hot paths read os.getenv directly)
  security.py        — require_dev_admin_token FastAPI dependency
  db/
    supabase_client.py — get_supabase_client() factory (server-side, service role key)
  services/
    classifier.py    — OpenAI classification + per-type structured_json schemas
    transcriber.py   — OpenAI Whisper transcription (Phase 10+)
  routes/
    health.py        — GET /health (public, no DB)
    health_db.py     — GET /health/db (protected, DB connectivity check)
    inbox.py         — GET /inbox (protected inbox read)
    classify.py      — POST /inbox/{id}/classify (recovery-only reclassify)
    review.py        — PATCH /inbox/{id}/confirm | /reject | edit (review actions)
    tasks.py         — GET /tasks, PATCH /tasks/{id}/complete (tasks module)
    finance.py       — GET /money_events (finance module, read-only)
    telegram.py      — POST /telegram/webhook (Telegram capture)
tests/
  test_health.py             — /health endpoint tests
  test_health_db.py          — /health/db endpoint tests (mocked Supabase)
  test_supabase_client.py    — unit tests for client factory
  test_inbox.py              — /inbox read tests (mocked Supabase)
  test_classifier.py         — classifier + schema validation tests
  test_classify_endpoint.py  — reclassify endpoint tests
  test_review.py             — confirm / reject / edit + task & finance confirm tests
  test_tasks.py              — tasks API tests (mocked Supabase)
  test_finance.py            — finance API tests (mocked Supabase)
  test_telegram_webhook.py   — Telegram text webhook tests (mocked Supabase + httpx)
  test_telegram_voice.py     — Telegram voice transcription tests (Phase 10)
```

## Environment variables

Copy the root `.env.example` to `services/api/.env.local` and fill in your values.

| Variable | Required for | Notes |
|---|---|---|
| `SUPABASE_URL` | `/health/db` and all DB routes | Project base URL only — no `/rest/v1/` path |
| `SUPABASE_ANON_KEY` | Future frontend read paths | Public key, lower privilege |
| `SUPABASE_SERVICE_ROLE_KEY` | All backend DB writes | **Server-side only. Never expose to frontend or commit.** |
| `DEV_ADMIN_TOKEN` | All non-webhook routes (Phases 4–15) | Generate: `python -c "import secrets; print(secrets.token_hex(32))"` |
| `TELEGRAM_BOT_TOKEN` | Sending confirmation replies | Best-effort — missing token skips reply but preserves capture |
| `TELEGRAM_WEBHOOK_SECRET` | `POST /telegram/webhook` | Set in BotFather when registering webhook; must match request header |
| `TELEGRAM_USER_ID` | `POST /telegram/webhook` | Your Telegram numeric user ID; missing = server misconfiguration (500) |
| `ANTHROPIC_API_KEY` | Possible future capabilities | Not required for Phase 6 classification |
| `OPENAI_API_KEY` | Phase 6 classification and Phase 10 transcription | Required for AI classification |

**`SUPABASE_SERVICE_ROLE_KEY`** is used only in `app/db/supabase_client.py`.
It must never appear in `apps/web/` env vars, browser bundles, or client responses.

## Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/health` | Public | Returns `{"status": "ok"}`. No DB, always fast. |
| `GET` | `/health/db` | `DEV_ADMIN_TOKEN` | Read-only DB connectivity check. |
| `GET` | `/inbox` | `DEV_ADMIN_TOKEN` | Returns pending + needs_manual_classification inbox items with embedded capture context. Newest first. |
| `POST` | `/inbox/{id}/classify` | `DEV_ADMIN_TOKEN` | **Recovery only** — reclassifies stubs (`item_type="unknown"`) from Phase 4/5 or failed classification. Returns 400 for confirmed, rejected, or already-classified items. Requires `OPENAI_API_KEY`; returns 503 if absent. |
| `PATCH` | `/inbox/{id}/confirm` | `DEV_ADMIN_TOKEN` | Confirms a pending inbox item. **Task** items use the `confirm_task_item` RPC → `{inbox_item, task}`; finance **expense** items use the `confirm_finance_item` RPC → `{inbox_item, money_event}` (each creates one linked domain row + sets `confirmed`/`reviewed_at` in one transaction). Finance **income** and module-less types set `review_status=confirmed`/`reviewed_at` only (status-only). Idempotent. |
| `PATCH` | `/inbox/{id}/reject` | `DEV_ADMIN_TOKEN` | Rejects a pending or needs_manual_classification item. Sets `review_status=rejected` and `reviewed_at`. Idempotent. |
| `PATCH` | `/inbox/{id}` | `DEV_ADMIN_TOKEN` | Edits a reviewable (pending or needs_manual_classification) item. Validates item_type and structured_json. Correcting a needs_manual item to a valid type returns it to pending. Never calls OpenAI. |
| `GET` | `/tasks` | `DEV_ADMIN_TOKEN` | Read-only list of confirmed tasks, newest first. |
| `PATCH` | `/tasks/{id}/complete` | `DEV_ADMIN_TOKEN` | Marks a task `completed` and sets `completed_at`. Idempotent. 404 if missing. No task editing. |
| `GET` | `/money_events` | `DEV_ADMIN_TOKEN` | Read-only list of confirmed expenses, newest first, with `totals_by_currency` (grouped by currency then category; currencies never summed together). |
| `POST` | `/telegram/webhook` | `TELEGRAM_WEBHOOK_SECRET` header | Telegram text and voice capture. Text → classify directly. Voice → download OGG → Whisper → classify. Non-text/voice updates silently ignored. |

`/telegram/webhook` uses its own secret (`X-Telegram-Bot-Api-Secret-Token` header), **not**
`DEV_ADMIN_TOKEN`. All other non-webhook routes use `DEV_ADMIN_TOKEN`.

## Development route protection

Until Phase 15 (auth/RLS), every non-webhook route uses `require_dev_admin_token`
from `app/security.py`. Pass: `Authorization: Bearer <your-dev-token>`.

The Telegram webhook validates its own `TELEGRAM_WEBHOOK_SECRET` independently.
`SUPABASE_SERVICE_ROLE_KEY` is never sent to the frontend.

If using ngrok or any public tunnel:
- Prefer exposing only `/telegram/webhook` path if the tunnel supports path routing.
- If the full backend is exposed, the `DEV_ADMIN_TOKEN` guard still applies to every
  non-webhook route. The tunnel does not bypass middleware.

## Telegram webhook flow (Phase 4)

```
Telegram sends POST /telegram/webhook
  → validate X-Telegram-Bot-Api-Secret-Token header
  → validate TELEGRAM_USER_ID matches sender (500 if not configured)
  → parse update JSON (non-text updates silently ignored)
  → check for duplicate via source_message_id = "{chat_id}:{message_id}"
    → if duplicate: ensure inbox_item exists (recovery), return duplicate_ignored
  → insert capture_events row (source="telegram_text", processing_status="received")
  → insert inbox_items row (item_type="unknown", review_status="pending") ← AI stub
  → send "✓ Captured" reply via Telegram Bot API (best-effort, failure preserved)
  → return {"status": "ok", "action": "captured"}
```

**Not implemented in Phase 4:** voice notes, AI classification, domain records, auth/RLS.

**`review_status = "pending"` with `item_type = "unknown"`** is a Phase 4 stub.
Phase 6 AI classification overwrites these with a real type, `structured_json`, and
`confidence`. Phase 7 added confirm / reject / edit; Phase 8 added atomic task confirmation.

**Duplicate safety:** migration 0005 adds `UNIQUE (source, source_message_id)` to
`capture_events` and `UNIQUE (capture_event_id)` to `inbox_items`. The application-layer
pre-check is the common path; if a concurrent insert wins the race and the INSERT fails, the
code re-queries, finds the existing row, and returns `duplicate_ignored` — no 500, no
duplicate row. If the inbox INSERT conflicts (concurrent recovery stub), the winning request
fetches the existing inbox_id and continues transcription/classification.

## How to run locally

```bash
cd services/api

# First time: create the venv and install deps
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt   # Windows
# source .venv/bin/activate && pip install -r requirements.txt  # macOS/Linux

# Start the server
.venv\Scripts\uvicorn app.main:app --reload     # Windows
# .venv/bin/uvicorn app.main:app --reload       # macOS/Linux
# → http://localhost:8000
# → http://localhost:8000/docs  (Swagger UI)
```

## How to run tests

```bash
cd services/api
.venv\Scripts\pytest          # Windows
# .venv/bin/pytest            # macOS/Linux
```

Expected: `186 passed` — no real Supabase, OpenAI, or Telegram calls.

## Local curl example — Telegram-like payload

```bash
curl -X POST http://localhost:8000/telegram/webhook \
  -H "Content-Type: application/json" \
  -H "X-Telegram-Bot-Api-Secret-Token: your-webhook-secret-here" \
  -d '{
    "update_id": 1001,
    "message": {
      "message_id": 42,
      "from": {"id": 123456789, "is_bot": false, "first_name": "Justin"},
      "chat": {"id": 123456789, "type": "private"},
      "date": 1700000000,
      "text": "Spent $12 on lunch at Tanjong Pagar"
    }
  }'
```

Replace `your-webhook-secret-here` with the value of `TELEGRAM_WEBHOOK_SECRET` in your
`.env.local`. The `from.id` and `chat.id` must match `TELEGRAM_USER_ID`.

Expected response:
```json
{"status": "ok", "action": "captured"}
```

## Phase 4 end-to-end verification (required to close Phase 4)

1. Fix `SUPABASE_URL` in `.env.local` — must be the bare project URL with no `/rest/v1/` suffix
2. Add `DEV_ADMIN_TOKEN` to `.env.local`
3. Add `TELEGRAM_BOT_TOKEN` and `TELEGRAM_WEBHOOK_SECRET` to `.env.local`
4. Set `TELEGRAM_USER_ID` to your numeric Telegram user ID
5. Start the backend: `uvicorn app.main:app --reload`
6. Expose the webhook: register with Telegram using ngrok or equivalent
   (prefer path-only exposure: `/telegram/webhook`)
7. Send a text message to your bot
8. Verify in Supabase dashboard:
   - One row in `capture_events` with `source="telegram_text"`, `processing_status="received"`
   - One linked row in `inbox_items` with `item_type="unknown"`, `review_status="pending"`
9. Verify the bot replies `✓ Captured`
10. Verify `GET /health/db` returns `{"status": "ok", "database": "connected"}`

## Phase history

- Phase 1: FastAPI scaffold, `GET /health`, pytest setup
- Phase 2: Database schema (`supabase/migrations/0001_capture_pipeline.sql`)
- Phase 3: Supabase client factory, DEV_ADMIN_TOKEN guard, `GET /health/db`
- Phase 4: Telegram text capture, `POST /telegram/webhook`, stub inbox_items
- Phase 5: Dashboard inbox read route, `GET /inbox` with embedded capture context, Pydantic response models
- Phase 6: AI classification, `app/services/classifier.py` (OpenAI gpt-4o-mini, JSON mode), `POST /inbox/{id}/classify`, agent_runs logging, failure lifecycle
- Phase 7: Review actions, `app/routes/review.py` — `PATCH /inbox/{id}/confirm`, `PATCH /inbox/{id}/reject`, `PATCH /inbox/{id}` (edit). Idempotent, concurrent-safe, no domain writes.
- Phase 8: Tasks module (MVP), `supabase/migrations/0002_tasks.sql` (`tasks` table + `confirm_task_item` atomic RPC), `app/routes/tasks.py` (`GET /tasks`, `PATCH /tasks/{id}/complete`), task branch in `confirm`. First atomic confirm-plus-domain-record; idempotent via UNIQUE `inbox_item_id`.
- Phase 9: Finance module, `supabase/migrations/0003_money_events.sql` (`money_events` table + `confirm_finance_item` atomic RPC), `app/routes/finance.py` (`GET /money_events` with currency/category totals), finance-expense branch in `confirm`. Expense-only; income confirms status-only. Currencies never summed together. ✓ complete.
- Phase 10: Voice transcription ✓ complete, `supabase/migrations/0004_capture_transcription_status.sql` (widens `processing_status` CHECK), `supabase/migrations/0005_capture_unique_source.sql` (UNIQUE on capture_events + inbox_items), `app/services/transcriber.py` (Whisper-1 service, English pinned), `telegram.py` extended with `TelegramVoice` model, `_transcribe_and_update`, and `_capture_voice` path. 25 MB audio limit enforced pre- and post-download. Two `agent_runs` rows on happy path (transcriber + text_classifier). All inbox INSERTs wrapped with conflict recovery so concurrent retries never produce duplicate inbox rows. Manual E2E passed.
