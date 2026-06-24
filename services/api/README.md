# services/api — Backend API

**Status: Phase 15b — memory-ready database foundation implemented; migrations/manual verification pending.**

`GET /portfolio` aggregates current positions, cash, and today's performance across Tiger and
IBKR, read-only. Brokers are fetched independently and concurrently with bounded per-broker
timeouts; one failing broker never hides the other (`partial_failure`). IBKR uses the Client
Portal Web API (httpx, GET-only allowlist) against a local gateway; Tiger uses the official
`tigeropen` SDK (lazy-imported). Totals are grouped per currency and never summed across
currencies, with per-metric completeness flags. No Supabase access, no broker writes, no
migration. See **Read-only enforcement** below.

Phase 13 (✓ complete): daily review — `GET /daily_review`. Phase 12 (✓ complete): calendar
intents. Phase 11 (✓ complete): food logs. Phase 10 (✓ complete): voice transcription.
Migrations `0001`–`0017` exist; `0009`–`0017` require manual application as applicable.
Replace `<OWNER_USER_ID>` in `0010_owner_id.sql`, `0011_memory_events.sql`,
`0013_exercise_logs.sql`, `0015_habits_goals.sql`, `0016_decisions.sql`, and
`0017_financial_snapshots.sql` with the Supabase owner UUID before applying them. Phase 17 also
requires a **private Supabase Storage bucket named `food-photos`** (food photos; signed-URL reads
only). 487 tests pass.

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
  security.py        — require_user Supabase JWT + owner-gate dependency
  db/
    supabase_client.py — get_supabase_client() factory (server-side, service role key)
  services/
    classifier.py    — OpenAI classification + per-type structured_json schemas
    transcriber.py   — OpenAI Whisper transcription (Phase 10+)
    portfolio_snapshot.py — pure normalization + atomic snapshot RPC call
  brokers/           — read-only portfolio adapters (Phase 14; no network at import time)
    models.py        — broker-neutral contract (Position, CashBalance, CurrencyTotal, …)
    masking.py       — mask_account() — never exposes full account numbers
    base.py          — BrokerAdapter ABC (read-only fetch_portfolio())
    tiger.py         — Tiger adapter (tigeropen, lazy-imported; SDK-method allowlist)
    ibkr.py          — IBKR adapter (CPAPI via httpx; GET-only path allowlist; TLS resolution)
    portfolio_service.py — concurrent orchestration, bounded executor, single-flight, totals
  routes/
    health.py        — GET /health (public, no DB)
    health_db.py     — GET /health/db (protected, DB connectivity check)
    inbox.py         — GET /inbox (protected inbox read)
    classify.py      — POST /inbox/{id}/classify (recovery-only reclassify)
    review.py        — PATCH /inbox/{id}/confirm | /reject | edit (review actions)
    tasks.py         — GET /tasks, PATCH /tasks/{id}/complete (tasks module)
    finance.py       — GET /money_events (finance module, read-only)
    food.py          — GET /food_logs (food module, read-only, ?date=today filter)
    calendar.py      — GET /calendar_intents (calendar module, read-only)
    daily_review.py  — GET /daily_review (read-only daily activity summary, Phase 13)
    portfolio.py     — GET /portfolio (read-only Tiger + IBKR portfolio, Phase 14)
    portfolio_snapshots.py — create/list/detail/history snapshot routes (Phase 14.5)
    telegram.py      — POST /telegram/webhook (Telegram capture)
tests/
  test_health.py             — /health endpoint tests
  test_health_db.py          — /health/db endpoint tests (mocked Supabase)
  test_supabase_client.py    — unit tests for client factory
  test_inbox.py              — /inbox read tests (mocked Supabase)
  test_classifier.py         — classifier + schema validation tests
  test_classify_endpoint.py  — reclassify endpoint tests
  test_review.py             — confirm / reject / edit + task, finance, food & calendar confirm tests
  test_tasks.py              — tasks API tests (mocked Supabase)
  test_finance.py            — finance API tests (mocked Supabase)
  test_food.py               — food logs API tests (mocked Supabase)
  test_calendar_intents.py   — calendar intents API tests (mocked Supabase)
  test_daily_review.py       — daily review API tests (mocked Supabase; 22 tests)
  test_portfolio.py          — /portfolio orchestration, totals, thread-accumulation (mocked adapters)
  test_portfolio_snapshot.py — normalization, allocation, missing fields, RPC idempotency
  test_portfolio_snapshots.py — snapshot route auth and response tests
  test_brokers_ibkr.py       — IBKR adapter: paths/methods, TLS, allowlist, normalization (mocked httpx)
  test_brokers_tiger.py      — Tiger adapter: SDK methods, normalization, allowlist (mocked SDK)
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
| `OWNER_USER_ID` | Single-user gate on protected routes | Owner UID from Authentication → Users. |
| `TELEGRAM_BOT_TOKEN` | Sending confirmation replies | Best-effort — missing token skips reply but preserves capture |
| `TELEGRAM_WEBHOOK_SECRET` | `POST /telegram/webhook` | Set in BotFather when registering webhook; must match request header |
| `TELEGRAM_USER_ID` | `POST /telegram/webhook` | Your Telegram numeric user ID; missing = server misconfiguration (500) |
| `ANTHROPIC_API_KEY` | Possible future capabilities | Not required for Phase 6 classification |
| `OPENAI_API_KEY` | Phase 6 classification and Phase 10 transcription | Required for AI classification |
| `USER_TIMEZONE` | `GET /food_logs?date=today` (Phase 11+), `GET /daily_review` (Phase 13+) | IANA timezone string, e.g. `Asia/Singapore`. `food.py` defaults to UTC if unset. `daily_review.py` requires it — missing or invalid IANA name → 503. |
| `IBKR_ENABLED` | `GET /portfolio` — IBKR (Phase 14) | `"true"` to enable; otherwise IBKR reports `not_configured`. Backend-only. |
| `IBKR_CPAPI_BASE_URL` | `GET /portfolio` — IBKR (Phase 14) | Client Portal Gateway base URL; default `https://localhost:5000/v1/api`. |
| `IBKR_CPAPI_CACERT` | `GET /portfolio` — IBKR (Phase 14) | Optional CA bundle/cert path. If set, TLS is verified. Otherwise insecure TLS is allowed **only** for loopback hosts; a remote host with no CA bundle is a config error. |
| `IBKR_ACCOUNT_LABEL` | `GET /portfolio` — IBKR (Phase 14) | Optional friendly label; otherwise the account is masked. |
| `TIGER_PROPS_PATH` | `GET /portfolio` — Tiger (Phase 14) | Backend-only. Directory holding Tiger's `tiger_openapi_config.properties` (carries `private_key_pk1`, `tiger_id`, `account`, `license`, `env`). Preferred config method; the SDK loads everything from it. Takes precedence over the explicit trio below. Keep the folder outside the repo. |
| `TIGER_ID`, `TIGER_ACCOUNT`, `TIGER_PRIVATE_KEY_PATH` | `GET /portfolio` — Tiger (Phase 14) | Backend-only. Explicit alternative to `TIGER_PROPS_PATH`. Private key must be PKCS#1. If `TIGER_PROPS_PATH` is unset, all three are required or Tiger reports `not_configured`. Never commit the key. |
| `TIGER_ACCOUNT_LABEL` | `GET /portfolio` — Tiger (Phase 14) | Optional friendly label; otherwise the account is masked. Applies to either config method. |
| `PORTFOLIO_BROKER_TIMEOUT` | `GET /portfolio` (Phase 14) | Per-broker fetch timeout in seconds (default 8). |

**`SUPABASE_SERVICE_ROLE_KEY`** is used only in `app/db/supabase_client.py`.
It must never appear in `apps/web/` env vars, browser bundles, or client responses.
**Broker credentials and account identifiers are backend-only**; they must never appear in
`apps/web/` env vars (no `NEXT_PUBLIC_` broker vars), browser bundles, responses, or logs.

## Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/health` | Public | Returns `{"status": "ok"}`. No DB, always fast. |
| `GET` | `/health/db` | `Supabase access token` | Read-only DB connectivity check. |
| `GET` | `/inbox` | `Supabase access token` | Returns pending + needs_manual_classification inbox items with embedded capture context. Newest first. |
| `POST` | `/inbox/{id}/classify` | `Supabase access token` | **Recovery only** — reclassifies stubs (`item_type="unknown"`) from Phase 4/5 or failed classification. Returns 400 for confirmed, rejected, or already-classified items. Requires `OPENAI_API_KEY`; returns 503 if absent. |
| `PATCH` | `/inbox/{id}/confirm` | `Supabase access token` | Confirms a pending inbox item. **Task** items use the `confirm_task_item` RPC → `{inbox_item, task}`; finance **expense** items use the `confirm_finance_item` RPC → `{inbox_item, money_event}` (each creates one linked domain row + sets `confirmed`/`reviewed_at` in one transaction). Finance **income** and module-less types set `review_status=confirmed`/`reviewed_at` only (status-only). Idempotent. |
| `PATCH` | `/inbox/{id}/reject` | `Supabase access token` | Rejects a pending or needs_manual_classification item. Sets `review_status=rejected` and `reviewed_at`. Idempotent. |
| `PATCH` | `/inbox/{id}` | `Supabase access token` | Edits a reviewable (pending or needs_manual_classification) item. Validates item_type and structured_json. Correcting a needs_manual item to a valid type returns it to pending. Never calls OpenAI. |
| `GET` | `/tasks` | `Supabase access token` | Read-only list of confirmed tasks, newest first. |
| `PATCH` | `/tasks/{id}/complete` | `Supabase access token` | Marks a task `completed` and sets `completed_at`. Idempotent. 404 if missing. No task editing. |
| `GET` | `/money_events` | `Supabase access token` | Read-only list of confirmed expenses, newest first, with `totals_by_currency` (grouped by currency then category; currencies never summed together). |
| `GET` | `/food_logs` | `Supabase access token` | Read-only list of confirmed food logs, newest first. `?date=today` filters by the user's local calendar day (based on `USER_TIMEZONE`), using `created_at` UTC boundaries — not `logged_at`. Only `date=today` or no param accepted; other values return 422. |
| `GET` | `/calendar_intents` | `Supabase access token` | Read-only list of all confirmed calendar intents, ordered by `created_at DESC`. `proposed_datetime` is verbatim text — not parsed. No date filter. |
| `GET` | `/daily_review` | `Supabase access token` | Read-only daily activity summary. Only `?date=today` or no param accepted; other values return 422. Requires `USER_TIMEZONE` — missing or invalid → 503. Returns captured/confirmed/rejected/pending counts, item lists, and a deterministic summary string. No AI call. |
| `GET` | `/portfolio` | `Supabase access token` | Read-only Tiger + IBKR portfolio. Brokers fetched independently/concurrently with bounded per-broker timeouts; one failing broker never hides the other (`partial_failure`, per-broker `status`). Returns normalized positions, account summaries, cash, and `totals_by_currency` (grouped per currency, never summed across currencies, with per-metric completeness). Account refs masked. No Supabase access, no broker writes. Returns 200 even when brokers are unconfigured/unavailable (the failure is reported in the body). |
| `POST` | `/portfolio/snapshots` | `Supabase access token` | Manually creates or refreshes today's atomic normalized snapshot. Idempotent per owner/local date. |
| `GET` | `/portfolio/snapshots` | `Supabase access token` | Lists snapshot dates, partial status, and per-currency totals, newest first. |
| `GET` | `/portfolio/snapshots/{date}` | `Supabase access token` | Returns one snapshot header, currency totals, and atomic position/cash rows. |
| `GET` | `/portfolio/snapshots/history?currency=USD` | `Supabase access token` | Returns date/total-value history for one native currency. No FX or chart math. |
| `POST` | `/telegram/webhook` | `TELEGRAM_WEBHOOK_SECRET` header | Telegram text and voice capture. Text → classify directly. Voice → download OGG → Whisper → classify. Non-text/voice updates silently ignored. |

`/telegram/webhook` uses its own secret (`X-Telegram-Bot-Api-Secret-Token` header), not a
user session. All other non-webhook routes require a valid owner Supabase access token.

## Read-only enforcement & residual risk (Phase 14 brokers)

`GET /portfolio` is read-only and enforces this in code, not by convention:

- **IBKR (CPAPI):** `IbkrAdapter._request` is the only network entry point and rejects any
  `(method, path)` not in a **GET-only allowlist** (auth status, accounts, summary, positions,
  ledger, pnl/partitioned). No POST/PUT/DELETE is reachable, so order endpoints cannot be called
  even by future code without editing the allowlist. No generic request method is exported.
  Local TLS: a CA bundle (`IBKR_CPAPI_CACERT`) is used when set; otherwise insecure TLS is
  permitted **only** for loopback hosts — a remote host without a CA bundle is a config error,
  never a silent downgrade.
- **Tiger (`tigeropen`):** `TigerAdapter` calls only allowlisted read methods (`get_positions`,
  `get_prime_assets`/`get_assets`) and never references `place_order`, `modify_order`,
  `cancel_order`, or any order/transfer method.
- **Residual risk:** broker-side read-only scoping is enabled where the broker supports it
  (e.g. IBKR's "Read-Only API" in TWS/IB Gateway config applies to the TWS API path). The CPAPI
  session inherits the logged-in user's full permissions — there is **no official per-session
  read-only scope** — so this is a documented residual risk, mitigated by the GET-only allowlist
  and the absence of any order code path. A compromised backend with a live session could call
  trading endpoints *only if such code were added*; Phase 14 ships none.

Broker credentials, private keys, account numbers, and raw broker responses never appear in
responses or logs. Account references are masked. Brokers run in a bounded thread pool with a
per-broker single-flight guard, so a hung broker cannot accumulate background threads.

## Authentication and route protection

Every non-webhook protected route uses `require_user` from `app/security.py`. It verifies
the Supabase ES256 access-token signature through the project's cached public JWKS, then
checks audience, expiry, and owner subject before the
service-role database client is used. Missing/invalid tokens return 401; a valid non-owner
token returns 403. `/health` remains public.

The Telegram webhook validates `TELEGRAM_WEBHOOK_SECRET` independently. Tunneling does not
bypass either guard. `SUPABASE_SERVICE_ROLE_KEY` remains backend-only; no JWT signing secret
is copied into the application.

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

Expected: `273 passed` — no real Supabase, OpenAI, or Telegram calls.

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
2. Add `OWNER_USER_ID` to `.env.local`; `SUPABASE_URL` identifies the public JWKS endpoint
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
- Phase 3: Supabase client factory, temporary development bearer-token guard, `GET /health/db`
- Phase 4: Telegram text capture, `POST /telegram/webhook`, stub inbox_items
- Phase 5: Dashboard inbox read route, `GET /inbox` with embedded capture context, Pydantic response models
- Phase 6: AI classification, `app/services/classifier.py` (OpenAI gpt-4o-mini, JSON mode), `POST /inbox/{id}/classify`, agent_runs logging, failure lifecycle
- Phase 7: Review actions, `app/routes/review.py` — `PATCH /inbox/{id}/confirm`, `PATCH /inbox/{id}/reject`, `PATCH /inbox/{id}` (edit). Idempotent, concurrent-safe, no domain writes.
- Phase 8: Tasks module (MVP), `supabase/migrations/0002_tasks.sql` (`tasks` table + `confirm_task_item` atomic RPC), `app/routes/tasks.py` (`GET /tasks`, `PATCH /tasks/{id}/complete`), task branch in `confirm`. First atomic confirm-plus-domain-record; idempotent via UNIQUE `inbox_item_id`.
- Phase 9: Finance module, `supabase/migrations/0003_money_events.sql` (`money_events` table + `confirm_finance_item` atomic RPC), `app/routes/finance.py` (`GET /money_events` with currency/category totals), finance-expense branch in `confirm`. Expense-only; income confirms status-only. Currencies never summed together. ✓ complete.
- Phase 10: Voice transcription ✓ complete, `supabase/migrations/0004_capture_transcription_status.sql` (widens `processing_status` CHECK), `supabase/migrations/0005_capture_unique_source.sql` (UNIQUE on capture_events + inbox_items), `app/services/transcriber.py` (Whisper-1 service, English pinned), `telegram.py` extended with `TelegramVoice` model, `_transcribe_and_update`, and `_capture_voice` path. 25 MB audio limit enforced pre- and post-download. Two `agent_runs` rows on happy path (transcriber + text_classifier). All inbox INSERTs wrapped with conflict recovery so concurrent retries never produce duplicate inbox rows. Manual E2E passed.
- Phase 11: Food logs module ✓ complete, `supabase/migrations/0006_food_logs.sql` (`food_logs` table + `confirm_food_item` atomic RPC), `app/routes/food.py` (`GET /food_logs` with `?date=today` filtering via `USER_TIMEZONE`-aware UTC boundaries), food branch in `confirm` (`review.py`). `logged_at` stored as verbatim TEXT; date filtering uses `created_at`. `tzdata` added to requirements for cross-platform timezone support. 235 tests pass.
- Phase 12: Calendar intents module ✓ complete, `supabase/migrations/0007_calendar_intents.sql` (`calendar_intents` table + `confirm_calendar_item` atomic RPC), `app/routes/calendar.py` (`GET /calendar_intents`), calendar branch in `confirm` (`review.py`). `proposed_datetime` stored as verbatim TEXT; no date filter; ordered by `created_at DESC`. No `status` column, no `user_id`. 248 tests pass.
- Phase 13: Daily review module ✓ complete, `app/routes/daily_review.py` (`GET /daily_review`). Three read-only queries: `capture_events.created_at` for captures (embedded inbox_items via reverse-FK select), `inbox_items.reviewed_at` for confirmed/rejected. `USER_TIMEZONE` required — missing or invalid → 503. Deterministic summary, no AI call, no migration. Automated and manual E2E verification passed. 273 tests pass.
- Phase 14: Read-only portfolio (implementation complete; manual verification pending), `app/brokers/` (models, masking, base, `tiger.py`, `ibkr.py`, `portfolio_service.py`) + `app/routes/portfolio.py` (`GET /portfolio`). IBKR via Client Portal Web API (httpx, GET-only allowlist, strict local-TLS); Tiger via `tigeropen` (lazy-imported, SDK-method allowlist). Concurrent fetch with bounded executor + per-broker single-flight; totals grouped per currency with per-metric completeness; account masking; no Supabase access; no migration. New deps: `tigeropen`. 317 tests pass (44 new, all mocked).
- Phase 14.5: Daily normalized portfolio snapshots, migration `0009_portfolio_snapshots.sql`,
  atomic service-role RPC, manual create/refresh, owner-scoped list/detail/history APIs, and
  minimal history UI. Postgres remains the source of truth; no FX, vectors, cron, or charts.
- Phase 15a: Supabase email/password authentication, ES256/JWKS owner verification on every
  non-webhook protected route, cookie-based Next.js sessions, and deny-by-default RLS migration
  `0008_rls_lockdown.sql`. Backend database access remains service-role. Manual setup pending.
- Phase 15b: Memory-ready database foundation, migrations `0010_owner_id.sql` and
  `0011_memory_events.sql`. All existing tables gain a default-filled, non-null `owner_id`;
  confirmation RPCs atomically append compact domain `memory_events`, while portfolio snapshot
  refreshes retain one `snapshot_created` event per canonical snapshot. No application routes,
  UI, summaries, embedding queue, embeddings, or vector store are added. Replace the owner UUID
  placeholder before manual migration application.
- Phase 17: Food calories/macros + photo input, migration `0012_food_nutrition.sql`
  (`food_logs` += calories/protein_g/carbs_g/fat_g/image_path; `capture_events.image_path`;
  `confirm_food_item` extended to persist nutrition + image, preserving the 15b memory event).
  `app/services/food_vision.py` (gpt-4o-mini image estimate), `app/services/storage.py`
  (private `food-photos` bucket upload + signed URLs), a Telegram photo capture path in
  `telegram.py`, and an extended text classifier so text food also gets estimates. Non-food
  photos → `needs_manual` (no fabricated meal). `GET /food_logs` returns nutrition + signed
  `image_url` + daily `totals`; the inbox exposes a signed `image_url` for food items.
  Manual setup: apply `0012` and create the `food-photos` bucket. Photos are sent to OpenAI for
  analysis (privacy note for the Phase 22 review).
- Phase 18: Exercise module ✓ complete, migrations `0013_exercise_logs.sql` (`exercise_logs` +
  `confirm_exercise_item` RPC with the 15b memory event + RLS + default-filled `owner_id`) and
  `0014_inbox_exercise_item_type.sql` (widen `inbox_items.item_type` to allow `exercise`).
  `app/routes/exercise.py` (`GET /exercise_logs` + `?date=today` + totals), classifier `exercise`
  type, exercise branch in `confirm`. `tests/test_item_type_constraint.py` guards that every
  classifier item_type is permitted by the DB CHECK.
- Phase 19: Daily Life Timeline ✓ complete (read-only), `app/routes/timeline.py` (`GET /timeline`:
  domain + ISO date-range filters, keyset cursor pagination over `memory_events`, `?from`→`from_`
  alias). No migration, no joins, no writes/AI. First read consumer of `memory_events`.
- Phase 20: Habits & Goals, migration `0015_habits_goals.sql` (`habits` + `goals` tables,
  `confirm_habit_item`/`confirm_goal_item` RPCs each writing one `memory_events` row, widened
  `inbox_items.item_type` for `habit`+`goal`, RLS, default-filled `owner_id`). `app/routes/habits.py`
  (`GET /habits`), `app/routes/goals.py` (`GET /goals`, `PATCH /goals/{id}/status` —
  active/achieved/abandoned, mirrors `tasks.complete`), classifier `habit`/`goal` types + schemas,
  habit/goal branches in `confirm`. Habits are definition-only; goal status changes do not write
  memory_events. Manual setup: apply `0015` (replace `<OWNER_USER_ID>`).
- Phase 22a: Financial Intelligence Layer, migration `0017_financial_snapshots.sql`
  (`manual_financial_snapshots` immutable JSONB-array table + `confirm_financial_snapshot_item` RPC,
  widened `inbox_items.item_type` for `financial_snapshot`, RLS, default-filled `owner_id`).
  Classifier `financial_snapshot` type + `FinancialSnapshotStructuredJson`; `app/services/
  financial_intelligence.py :: compute_summary()` (pure, deterministic, per-currency);
  `GET /financial_snapshots`, `GET /financial_intelligence/summary` (net worth/cash/invested/
  liabilities/income/logged-expenses/savings/investment/runway, by currency, missing→unavailable).
  Monthly-expense windows use `money_events.created_at` with USER_TIMEZONE month boundaries. No
  cross-currency total, no AI numbers, no advice. Manual setup: apply `0017`
  (replace `<OWNER_USER_ID>`).
- Phase 22b-1: Monthly explanation, `GET /financial_intelligence/monthly` (pure `compute_monthly()`),
  no migration. Per-currency current-vs-previous-month logged expenses + Δ, logged savings rate + Δ,
  manual-position change (≥2 manual snapshots), portfolio total_value change (≥2 portfolio
  snapshots, labeled with dates + partial), deterministic explanation strings. Previous month only
  if ≥1 expense predates the current month. A "This month" section on `/financial-intelligence`.
  Financial-goal progress (22b-2) is still deferred.
- Phase 21: Decision Journal, migration `0016_decisions.sql` (`decisions` table +
  `confirm_decision_item` RPC writing one `memory_events` row, widened `inbox_items.item_type` for
  `decision`, RLS, default-filled `owner_id`). `app/routes/decisions.py` (`GET /decisions`,
  `PATCH /decisions/{id}/status` — active/reversed/archived, mirrors goals), classifier `decision`
  type + `DecisionStructuredJson` + conservative disambiguation, decision branch in `confirm`, and
  full timeline integration. Status changes do not write memory_events. Manual setup: apply `0016`
  (replace `<OWNER_USER_ID>`).
