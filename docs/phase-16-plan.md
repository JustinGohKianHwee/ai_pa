# Phase 16 — Production Deployment (plan + runbook)

## Context
Phases 1–15c are on `main`: the full capture → review → confirm pipeline, domain modules
(tasks/finance/food/calendar), read-only portfolio + daily snapshots, Supabase ES256 auth +
RLS, the memory-ready foundation (owner_id + memory_events), and the dark-cockpit UI. It all
runs **locally only**. Phase 16 deploys it so you can capture from your phone and use it daily
— which is what makes the accumulating data (and the future memory/LLM layer) worthwhile.

This is mostly **manual provisioning** (your accounts/dashboards) plus a few small repo files.
No feature work.

## Decisions (confirmed)
- **Frontend → Vercel** (native Next.js).
- **Backend → Render, free tier** for now (accept cold-start lag; upgrade to Starter later for
  always-on + native cron).
- **Supabase → reuse the current project** as production (migrations 0001–0011 already applied,
  owner user exists, data present).
- **Portfolio in prod = Tiger only.** IBKR's Client Portal Gateway is a local Java app needing
  interactive browser SSO — it can't run on a PaaS, so leave `IBKR_ENABLED` unset in prod
  (the portfolio page will show IBKR as "not configured", Tiger works normally).
- **Scheduled 7am snapshot = deferred.** Render's native Cron is a paid feature and the free
  web service sleeps. Use the manual "Snapshot today" button for now; add the scheduled job
  when you upgrade (see "Deferred").

## Architecture
```
Phone → Telegram → webhook → Render (FastAPI, free) ─ service-role ─> Supabase (reused prod)
Browser → Vercel (Next.js) ── server-side authedFetch (user JWT) ──> Render backend
                         └── Supabase Auth (login) directly
```
Frontend→backend calls are **server-side** (Next server components/actions), so **no browser
CORS is needed** — don't add CORS middleware.

## Part A — Small repo changes (the only code/config work)
1. **Pin Python for Render** — add `services/api/runtime.txt` containing `python-3.11.x`
   (or set `PYTHON_VERSION` env on Render). Ensures the build uses 3.11+.
2. **`.env.example`** — add a short "Production (Render)" note listing the backend env vars to
   set in the dashboard (below) and that `IBKR_*` is omitted in prod. Placeholders only.
3. **READMEs** — add a "Deployment" section (this runbook, condensed): Vercel for the frontend,
   Render for the backend, reused Supabase, Telegram webhook re-registration, the Tiger
   secret-file step, and the IBKR/scheduled-snapshot caveats.
   No application code changes are required for the free-tier deploy.

## Part B — Manual provisioning (you, in the dashboards)

### B1. Backend → Render (free Web Service)
- New → Web Service → connect the GitHub repo.
- **Root directory:** `services/api`
- **Build command:** `pip install -r requirements.txt`
- **Start command:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- **Instance type:** Free.
- **Environment variables:** `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_ANON_KEY`,
  `OWNER_USER_ID`, `OPENAI_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`,
  `TELEGRAM_USER_ID`, `USER_TIMEZONE=Asia/Singapore`, `PORTFOLIO_BROKER_TIMEOUT=8`,
  `TIGER_PROPS_PATH` (see B2). **Do not set `IBKR_ENABLED`.** **Do not set `DEV_ADMIN_TOKEN`**
  (removed in 15a).
- Health check path: `/health`.
- Note the assigned URL, e.g. `https://ai-pa-api.onrender.com`.

### B2. Tiger key on Render (Secret Files)
- In the Render service → **Secret Files**, upload your Tiger config (`tiger_openapi_config.properties`
  + key) to a mounted path, e.g. `/etc/secrets/tiger/`.
- Set `TIGER_PROPS_PATH=/etc/secrets/tiger` (the directory). Done — no code change.
- (Fallback if secret files don't fit: store the PKCS#1 key in an env var and write it to a
  file at startup — a small code addition. Prefer secret files.)

### B3. Frontend → Vercel
- New Project → import the repo → **Root directory:** `apps/web`.
- **Environment variables:** `NEXT_PUBLIC_API_URL=https://<your-render-url>`,
  `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`. (All public-safe; no service-role
  key, no DEV token.)
- Deploy. Note the Vercel URL, e.g. `https://ai-pa.vercel.app`.

### B4. Supabase (reused project)
- **Auth → URL configuration:** set Site URL to the Vercel URL and add it to redirect allowlist.
- Confirm public sign-ups stay **disabled** and the owner user exists (from 15a).
- Nothing else — migrations + data are already there.

### B5. Telegram webhook → prod
- Re-register the webhook to the Render backend:
  `https://api.telegram.org/bot<token>/setWebhook?url=https://<render-url>/telegram/webhook&secret_token=<TELEGRAM_WEBHOOK_SECRET>`
- (This replaces the local ngrok webhook. You can keep ngrok for local dev on a different token.)

## Part C — Verification (prod E2E)
1. Open the Vercel URL logged out → redirected to `/login`.
2. Log in with the owner account → dashboard loads. (First load may take ~30–60s while the free
   backend cold-starts; subsequent loads are fast until it idles again.)
3. Message the Telegram bot → the item appears in the inbox (allow for cold-start on the first
   message after idle; Telegram retries).
4. Confirm an item → domain record created; a `memory_events` row is written.
5. Portfolio page → Tiger loads; IBKR shows "Not configured" (expected in prod).
6. "Snapshot today" → succeeds; `/portfolio/history` renders.
7. Secret scan: view-source / network on the Vercel app → only the anon key is present; no
   service-role key, no JWT secret, no Tiger key.

## Deferred (do when you upgrade to Render Starter)
- **Scheduled 7am-SGT snapshot:** add a tiny CLI entry (`python -m app.scripts.snapshot` calling
  `create_today_snapshot()` with `OWNER_USER_ID` from env — no HTTP/JWT needed) and a Render
  Cron Job running it at the SGT-equivalent UTC time. Label `snapshot_date` as the US trading
  day. (Free tier: skip; use the manual button.)
- **Always-on:** upgrade to Starter to kill cold-start lag on captures and page loads.
- **IBKR in prod:** only if you run the Client Portal Gateway on a persistent home server/VPS
  and point the backend at it (networking + keepalive); otherwise IBKR stays a local-only feature.

## Out of scope
No new features, no IBKR-in-prod, no automated scheduling (free tier), no custom domain, no
new Supabase project, no CORS middleware (frontend→backend is server-side).

## Definition of done
Sending a Telegram message from your phone creates an inbox item visible at the Vercel URL; you
can log in, review/confirm, see tasks/finance/food/calendar, load the Tiger portfolio, and take
a snapshot — all in production, with no secrets exposed to the browser.
