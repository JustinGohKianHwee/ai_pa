# Phase 15a — Authentication + RLS (plan for Codex execution)

> **Workflow:** Claude Code authored this plan; **Codex executes it**. Do not make
> architectural decisions — if anything here is ambiguous, stop and ask rather than
> choosing. Recommended Codex settings: **model 5.5, effort high** (security-critical,
> many interdependent files).

---

## Context

Phases 1–14 are complete. Until now every non-webhook route has been guarded by a shared
`DEV_ADMIN_TOKEN` bearer (development only). Phase 15a replaces that with real Supabase
authentication and locks the database down with Row-Level Security (RLS). Vector/semantic
memory is **explicitly deferred to Phase 15b** and is out of scope here.

### Confirmed decisions (made with the user — do not revisit)

1. **Single-user.** Only the owner authenticates. **No `user_id` columns, no ownership
   model, no multi-tenancy.** RLS is a lockdown/defense-in-depth layer, not per-user isolation.
2. **Service-role backend + API-layer auth.** The FastAPI backend keeps using the Supabase
   **service-role key** for all DB access (it bypasses RLS). Security is enforced by
   requiring a valid Supabase session on every protected route. RLS is the backstop that
   blocks any direct/anon access if a key leaks. **Do not** switch the data layer to per-user
   JWTs.
3. **Email + password** login via Supabase Auth.

---

## Architecture overview

```
Browser ──(email+password)──> Supabase Auth ──issues JWT──> stored in cookies (@supabase/ssr)
   │
   │  Next.js server components / server actions read the access token from cookies
   ▼
Authorization: Bearer <supabase access_token>
   │
   ▼
FastAPI  require_user dependency:
   - verify JWT (ES256 via Supabase JWKS, aud="authenticated", exp)
   - enforce sub == OWNER_USER_ID  (single-user gate)
   │  (backend still uses SERVICE-ROLE key for DB — bypasses RLS)
   ▼
Supabase Postgres  (RLS enabled on all tables; anon/authenticated denied; service_role bypasses)
```

The Telegram webhook is **unchanged** — it is machine-to-machine, authenticated by its own
`TELEGRAM_WEBHOOK_SECRET`, and has no user session. It continues to write capture rows.

---

## Part A — Backend: replace the dev-token guard with Supabase JWT verification

### A1. New dependency `require_user` (`app/security.py`)

Replace `require_dev_admin_token` with `require_user`. Signature and behavior:

```python
# require_user(authorization: str | None = Header(default=None)) -> str
# Returns the authenticated user's id (sub). Raises HTTPException otherwise.
```

Verification steps, in order:
1. Read `SUPABASE_URL` and `OWNER_USER_ID` from env. If either is missing → **500**
   (`"Server misconfiguration: auth is not configured"`).
2. Require an `Authorization: Bearer <token>` header. Missing/malformed → **401**.
3. Use a cached `PyJWKClient` against
   `<SUPABASE_URL>/auth/v1/.well-known/jwks.json` to select the public key by `kid`, then
   decode with `algorithms=["ES256"]`, `audience="authenticated"`, required `exp/sub/aud`,
   and a 10-second clock-skew leeway.
   - `ExpiredSignatureError` → **401** (`"Token expired"`).
   - JWKS connectivity failure → **503** (`"Authentication service unavailable"`).
   - Unknown `kid` or any other `InvalidTokenError` (bad signature, wrong audience,
     malformed) → **401**
     (`"Invalid token"`).
4. Single-user gate: if `payload.get("sub") != OWNER_USER_ID` → **403** (`"Forbidden"`).
5. Return `payload["sub"]`.

Notes:
- Accept only **ES256** access tokens and use Supabase's public JWKS. Cache the JWKS for five
  minutes and use a five-second fetch timeout. Never copy a JWT signing secret/private key.
- Never log the token or its contents.
- Keep the dependency synchronous (no I/O — it only verifies a signature).

### A2. Config + env (`app/config.py`, `.env.example`)

- Add the `OWNER_USER_ID` reference in `config.py` (same `os.getenv`
  documentation pattern as existing entries).
- `.env.example` (backend section): add `OWNER_USER_ID=` with a comment explaining where to
  get it. Existing `SUPABASE_URL` identifies the JWKS endpoint. **Remove `DEV_ADMIN_TOKEN`**
  and its note.
- Frontend `.env.local` guidance: replace the `DEV_ADMIN_TOKEN` line with
  `NEXT_PUBLIC_SUPABASE_URL=` and `NEXT_PUBLIC_SUPABASE_ANON_KEY=` (both are public-safe;
  the anon key is designed to be exposed and RLS protects the data).

### A3. Swap the dependency in every protected route

Replace `Depends(require_dev_admin_token)` with `Depends(require_user)` in all of:
`routes/inbox.py`, `routes/classify.py`, `routes/review.py`, `routes/tasks.py`,
`routes/finance.py`, `routes/food.py`, `routes/calendar.py`, `routes/daily_review.py`,
`routes/portfolio.py`, `routes/health_db.py`.

Leave **`routes/health.py`** open (liveness, no auth) and **`routes/telegram.py`** on its
existing webhook-secret guard (do **not** add `require_user` to the webhook).

Routes do not need the returned user id in single-user mode; keep them as
`dependencies=[Depends(require_user)]` where they currently use `dependencies=[...]`, or as a
parameter where they currently take one. Match each route's existing style.

### A4. Remove `DEV_ADMIN_TOKEN`

Delete `require_dev_admin_token` and remove `DEV_ADMIN_TOKEN` from **shipped code, active
configuration, and active docs guidance** (`.env.example`, the READMEs' setup/security
sections, `apps/web`) once routes are migrated. Do not leave a dual-auth fallback.

**Scope exception:** this planning doc (`docs/phase-15a-plan.md`) and any *historical*
phase-history references (e.g. "Phases 4–14 used a `DEV_ADMIN_TOKEN` guard") intentionally
retain the name to describe what was removed. They are not active usage and must not be
scrubbed.

### A5. Dependencies

Add `pyjwt[crypto]>=2.8.0` to `services/api/requirements.txt`.

---

## Part B — Database: RLS lockdown migration

Create `supabase/migrations/0008_rls_lockdown.sql`. Goal: with the backend on the
service-role key (which **bypasses RLS**), lock every table and RPC so the anon/authenticated
roles can reach nothing.

For **every** table — `capture_events`, `inbox_items`, `agent_runs`, `tasks`,
`money_events`, `food_logs`, `calendar_intents`:
```sql
ALTER TABLE <t> ENABLE ROW LEVEL SECURITY;
ALTER TABLE <t> FORCE ROW LEVEL SECURITY;          -- optional but explicit
REVOKE ALL ON TABLE <t> FROM anon, authenticated;  -- belt-and-suspenders
-- No permissive policies are created → deny-by-default for anon/authenticated.
```
Service role bypasses RLS, so the backend keeps full access with no policy needed.

For the confirm RPCs — `confirm_task_item`, `confirm_finance_item`, `confirm_food_item`,
`confirm_calendar_item`:
```sql
REVOKE ALL ON FUNCTION <fn>(<args>) FROM public, anon, authenticated;
GRANT EXECUTE ON FUNCTION <fn>(<args>) TO service_role;
```
First **inspect each function's signature and SECURITY mode** in its migration (0002/0003/
0006/0007). Match the exact argument list in the REVOKE/GRANT. If a function is
`SECURITY DEFINER`, confirm it is owned by a privileged role; the REVOKE-from-public +
GRANT-to-service_role is still correct.

Update the README migration list to include `0008` and the "applied" note.

> Codex: this migration is **applied manually** by the user in the Supabase SQL editor (same
> as prior migrations). Do not attempt to run it.

---

## Part C — Frontend: Supabase Auth (Next.js)

### C1. Dependencies
Add `@supabase/supabase-js` and `@supabase/ssr` to `apps/web`.

### C2. Supabase client helpers
Create cookie-based helpers using `@supabase/ssr`:
- `apps/web/lib/supabase/server.ts` — `createServerClient` reading/writing cookies (for
  server components and server actions).
- `apps/web/lib/supabase/client.ts` — `createBrowserClient` (for the login form / client UI).
- `apps/web/lib/supabase/middleware.ts` — session-refresh helper used by middleware.

Use the env vars `NEXT_PUBLIC_SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_ANON_KEY`.

### C3. Login page
`apps/web/app/login/page.tsx` — a client component with an email + password form calling
`supabase.auth.signInWithPassword`. On success, redirect to `/`. Show a clear error on
failure. This is the only public page.

### C4. Middleware
`apps/web/middleware.ts` — refresh the Supabase session cookie on each request and **redirect
unauthenticated requests to `/login`** for all routes except `/login` and static assets.
Configure the matcher to exclude `_next/static`, `_next/image`, favicon, etc.

### C5. Authenticated fetch helper (replaces DEV_ADMIN_TOKEN)
Create `apps/web/lib/api.ts` exporting a server-side `authedFetch(path, init?)` that:
- reads the current Supabase **access token** from the server client session,
- sets `Authorization: Bearer <access_token>` and `NEXT_PUBLIC_API_URL` base,
- on a 401 from the backend, surfaces it so the caller can redirect to `/login`.

Refactor all current `DEV_ADMIN_TOKEN` call sites to use it:
- Pages (server components): `app/inbox/page.tsx`, `app/tasks/page.tsx`,
  `app/finance/page.tsx`, `app/food/page.tsx`, `app/calendar/page.tsx`,
  `app/review/page.tsx`, `app/portfolio/page.tsx`.
- Server actions: `app/inbox/actions.ts`, `app/tasks/actions.ts` (replace their local
  `token()` / `callApi` token logic with `authedFetch`).
Remove every `process.env.DEV_ADMIN_TOKEN` reference from `apps/web`.

### C6. Logout
Add a **Logout** control (e.g. on the home page header) that calls `supabase.auth.signOut`
and redirects to `/login`.

### C7. 401 handling
When `authedFetch` sees a 401 (expired/again-unauthenticated), redirect the user to `/login`
rather than rendering an error.

---

## Part D — Manual Supabase setup (user-performed; document in README)

Document these steps clearly; they are prerequisites, performed by the user in the Supabase
dashboard — Codex cannot do them:
1. **Create the owner user** (email + password) under Authentication → Users (or sign up once
   then disable signups).
2. **Disable public sign-ups** (Authentication → Providers/Settings) so no one else can
   register — critical for single-user.
3. For a private tool, **disable email confirmation** (or confirm the owner manually) so login
   works without an email round-trip.
4. Copy the owner's **user UID** (Authentication → Users) → backend `OWNER_USER_ID`.
   The backend derives the public JWKS endpoint from `SUPABASE_URL`.
5. Copy **Project URL** and **anon key** → frontend `NEXT_PUBLIC_SUPABASE_URL` /
   `NEXT_PUBLIC_SUPABASE_ANON_KEY`.
6. Apply migration `0008_rls_lockdown.sql` in the SQL editor.

---

## Part E — Tests

### E1. Backend auth unit tests (`tests/test_security.py`, new)
Generate ES256 tokens with a test EC key pair and mock the JWKS signing-key retrieval boundary,
while explicitly asserting that production decode is restricted to ES256. Cover:
- valid owner token → dependency returns the sub, route returns 200;
- expired token → 401;
- bad signature (wrong secret) → 401;
- wrong audience → 401;
- `sub` ≠ `OWNER_USER_ID` → 403;
- missing/malformed Authorization header → 401;
- missing `SUPABASE_URL` or `OWNER_USER_ID` → 500;
- JWKS connection failure → 503 and unknown `kid` → 401.

### E2. Shared auth fixture/helper (`tests/conftest.py`)
Add a helper that sets `SUPABASE_URL` + `OWNER_USER_ID` (test values), provides the test
public key at the JWKS boundary, and mints a valid
owner Bearer token, plus a fixture exposing an `auth_header()`granting it. **Every existing
route test** currently sets `DEV_ADMIN_TOKEN` and sends `Bearer <token>`; refactor them to use
this helper. This is mechanical but touches all route test files
(`test_inbox`, `test_tasks`, `test_finance`, `test_food`, `test_calendar`,
`test_daily_review`, `test_review`, `test_portfolio`, `test_classify`, `test_health_db`).
Keep the existing broker-env isolation fixture.

### E3. Negative-path route test
At least one protected route returns **401 without a token** and **403 with a non-owner
token**, proving the guard is wired through FastAPI (not just unit-tested in isolation).

### E4. Frontend
`npm run lint`, `npx tsc --noEmit`, `npm run build` must all pass. No new frontend unit-test
framework is required; auth flow is verified manually (Part F).

### E5. RLS
RLS is verified **manually** (Part F) — pytest has no live Postgres. Do not add a DB-network
test.

---

## Part F — Verification (run before handing back / before "phase done")

Automated:
```
cd services/api && .venv/Scripts/pytest -q          # all green, incl. new auth tests
cd apps/web && npm run lint && npx tsc --noEmit && npm run build
git diff --check
```
Secret scan: no `DEV_ADMIN_TOKEN` in **shipped code or active config** — i.e. none under
`services/api/app/`, `apps/web/` (excluding READMEs' historical notes), or `.env.example`.
The planning doc and historical phase-history mentions are exempt (see A4). Concretely, this
must be empty:
`git grep -n DEV_ADMIN_TOKEN -- services/api/app apps/web ':!*.md'`
Also: no JWT secret or service-role key in frontend bundles; `.env.example` placeholders only.

Manual (user, before marking the phase complete):
1. Apply migration 0008; set backend `OWNER_USER_ID` (with existing `SUPABASE_URL`); set frontend
   Supabase env; create owner user; disable signups.
2. Visit any dashboard page while logged out → redirected to `/login`.
3. Log in with the owner email/password → redirected in, data loads.
4. Call a protected API route with **no** token → 401; with a **non-owner** token → 403.
5. Using the Supabase **anon key**, attempt to read each table and call a confirm RPC directly
   → all denied (RLS + revoked grants). Using the **service-role** key → succeeds.
6. Log out → redirected to `/login`, dashboard no longer accessible.
7. Telegram capture still works (webhook unchanged) and confirmed items still flow through the
   review pipeline.

---

## Out of scope (do NOT build in 15a)
- Vector/semantic memory, `memory_chunks`, pgvector, embeddings, `/memory/search` (→ 15b).
- Multi-user, `user_id` columns, per-user RLS policies, ownership checks.
- OAuth / magic-link / password-reset / email-verification flows beyond basic email+password.
- Deployment (Phase 16).
- Any change to the capture → inbox → review → confirm pipeline semantics.

---

## Documentation to update (part of the phase)
- `services/api/README.md` — auth model, `require_user`, new env vars, removal of
  `DEV_ADMIN_TOKEN`, migration 0008, test count.
- root `README.md` — security note + current status → Phase 15a.
- `docs/roadmap.md` — Phase 15a status; note 15b (vector memory) still pending.
- `apps/web/README.md` — Supabase auth env vars; remove `DEV_ADMIN_TOKEN`.

---

## Key risks / gotchas (flagged for Codex)
- **Test refactor blast radius.** Every route test uses the dev token. Centralize the new
  token helper in `conftest.py` so the change is one helper + mechanical edits, not bespoke
  per file.
- **Service-role still bypasses RLS** — that is intended. Do not "fix" the backend to respect
  RLS; the chosen model is API-layer auth + RLS backstop.
- **RPC grants** must match exact function signatures from earlier migrations — inspect them.
- **`@supabase/ssr` cookie handling** in Next.js 15 App Router is specific; follow the current
  `@supabase/ssr` server/middleware pattern (getAll/setAll cookies), not the deprecated
  `auth-helpers` package.
- **Don't lock yourself out:** disabling sign-ups must come *after* the owner user exists.
