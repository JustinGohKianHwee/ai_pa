# Phase 14.5 — Daily Normalised Portfolio Snapshots (plan for Codex execution)

> **Workflow:** Claude Code authored this plan; **Codex executes it**. Do not make
> architectural decisions — if anything is ambiguous, stop and ask. Recommended Codex
> settings: **model 5.5, effort high**.

---

## Context & principle

Phases 1–14 + 15a (Supabase ES256 auth + RLS) are complete. Phase 14 exposed a **read-only**,
**live** portfolio (`GET /portfolio`) with **no stored portfolio tables**. Phase 14.5 persists
**one canonical, normalised portfolio state per day** for historical analysis and as a future
feeder for LLM memory.

- **Postgres stays the source of truth.** No vector DB, embeddings, or FX in this phase.
- Snapshots are **observational** records derived from the broker fetch — they do **not** flow
  through the capture→inbox→confirm pipeline (that is for user-asserted captures; a snapshot is
  a broker fact). They remain broker-read-only (no trades).
- This introduces the **first portfolio DB tables**.

### Confirmed decisions (do not revisit)
1. **Per-currency totals, no FX.** No single grand total; group per currency (consistent with
   Phase 14's no-FX rule).
2. **`owner_id` now** — `text NOT NULL` storing the owner id (single-user today, forward-compat).
3. **Idempotent upsert per `(owner_id, snapshot_date)`** — no versioning.
4. **Manual trigger only** (button/endpoint). Cron/scheduling deferred to post-deployment.

---

## Part A — Migration `supabase/migrations/0009_portfolio_snapshots.sql`

Three tables + RLS lockdown (mirror `0008`) + one service-role-only atomic RPC.

**`portfolio_snapshots`** (one per owner per date)
`id uuid pk default gen_random_uuid()` · `owner_id text not null` · `snapshot_date date not null`
· `generated_at timestamptz not null` · `source text not null` · `partial_failure boolean not
null default false` · `broker_status_json jsonb not null default '{}'` · `created_at timestamptz
not null default now()` · `updated_at timestamptz not null default now()` ·
**`unique (owner_id, snapshot_date)`**

**`portfolio_snapshot_currency_totals`** (per-currency rollup — the "totals", no FX)
`id uuid pk` · `snapshot_id uuid not null references portfolio_snapshots(id) on delete cascade`
· `owner_id text not null` · `currency text not null` · `market_value numeric not null default 0`
· `cash_value numeric not null default 0` · `invested_value numeric not null default 0` ·
`total_value numeric not null default 0` · `market_value_complete boolean not null default true`
· `market_value_missing int not null default 0` · **`unique (snapshot_id, currency)`**

**`portfolio_snapshot_positions`** (atomic holdings — one row per position + one per cash balance)
`id uuid pk` · `snapshot_id uuid not null references portfolio_snapshots(id) on delete cascade` ·
`owner_id text not null` · `broker text not null` · `account_ref text not null` (already masked)
· `asset_symbol text not null` · `asset_name text` · `asset_type text not null` (`asset_class`;
`'cash'` for cash rows) · `instrument_id text` · `stable_asset_id text not null` (queryable
cross-snapshot key — see normalisation) · `quantity numeric` · `price numeric` ·
`market_value numeric` · `average_cost numeric` · `cost_basis numeric` · `unrealized_pnl numeric`
· `today_pnl numeric` · `currency text not null` · `allocation_pct numeric` · `quote_status text`
· `metadata_json jsonb not null default '{}'` · `created_at timestamptz not null default now()`

**RLS + grants:** for all three tables, `enable row level security` + `force row level security`
+ `revoke all ... from anon, authenticated` (no policies → deny-by-default; service_role
bypasses). Reuse the existing `set_updated_at()` trigger (migration 0001) for
`portfolio_snapshots.updated_at`.

**Atomic RPC** `create_portfolio_snapshot(p_owner_id text, p_snapshot_date date, p_generated_at
timestamptz, p_source text, p_partial_failure boolean, p_broker_status jsonb, p_currency_totals
jsonb, p_positions jsonb) returns uuid` — PL/pgSQL, **single transaction**, modelled on
`confirm_task_item` (0002): upsert header on `(owner_id, snapshot_date)`; delete existing child
rows for that snapshot id; insert currency-totals and positions from the JSON arrays; return the
snapshot id. Lock down: `revoke all on function ... from public, anon, authenticated; grant
execute ... to service_role;`. (Supabase Python calls aren't transactional across tables, so the
RPC is required.)

> **Do not apply the migration** — the user applies it manually in the Supabase SQL editor.
> Update the README migration list to include `0009`.

---

## Part B — Backend

**`app/services/portfolio_snapshot.py`** (new)
- `normalize_snapshot(portfolio: PortfolioResponse, owner_id: str, snapshot_date: date) ->
  tuple[dict, list[dict], list[dict]]` — **pure, deterministic, no I/O** (header, currency_totals,
  positions). Rules:
  - Only brokers with `status == ok` contribute positions. Each `Position` → one row; each
    `CashBalance` → one row with `asset_type='cash'`, `asset_symbol=currency`, `quantity=amount`,
    `price=1`, `market_value=amount`, `currency=currency`.
  - `partial_failure` = `PortfolioResponse.partial_failure`; `broker_status_json` =
    `{broker: status}` for all brokers.
  - `stable_asset_id` = `instrument_id` if present, else `f"{broker}:{asset_symbol}:{currency}"`
    (stored as a first-class column for cross-snapshot joins; never null).
  - Per currency: `cash_value` = Σ cash; `invested_value` = `market_value` = Σ non-cash
    market_value; `total_value` = invested + cash. `market_value_missing` = count of non-cash
    positions with null market_value; `market_value_complete` = (missing == 0).
  - `allocation_pct` = `market_value / currency.total_value * 100`, rounded 2 dp; **null** if the
    position's market_value is null or the currency total is 0. Cash rows get an allocation_pct too.
  - `cost_basis` = `average_cost * quantity` when `average_cost` present, else null. Never
    fabricate prices/costs.
  - Store full numeric precision; round only `allocation_pct`.
- `create_today_snapshot() -> dict` — resolve `OWNER_USER_ID` and today's date in `USER_TIMEZONE`
  (reuse the tz/today helper used by `daily_review.py`), call
  `app.brokers.portfolio_service.fetch_portfolio()`, `normalize_snapshot(...)`, then
  `get_supabase_client().rpc("create_portfolio_snapshot", {...})`. Return a small summary
  (snapshot_date, currency totals, partial_failure, position count).

**`app/routes/portfolio_snapshots.py`** (new) — all `Depends(require_user)`:
- `POST /portfolio/snapshots` — create/refresh today's snapshot (idempotent).
- `GET /portfolio/snapshots` — list `{snapshot_date, partial_failure, currency_totals}` desc.
- `GET /portfolio/snapshots/{date}` — header + currency totals + positions (404 if absent).
- `GET /portfolio/snapshots/history?currency=USD` — `[{snapshot_date, total_value}]` for one
  currency (simple; no chart math).
- Register the router in `app/main.py`.

**Reuse:** `portfolio_service.fetch_portfolio`, `get_supabase_client`, `require_user`, the
tz/today helper from `daily_review.py`, `set_updated_at()` in SQL. Account refs are already
masked in `Position.account_ref`.

---

## Part C — Frontend (minimal; no chart infra exists → no charts)
- [apps/web/app/portfolio/page.tsx](apps/web/app/portfolio/page.tsx): add a **"Snapshot today"**
  button wired to a server action (`apps/web/app/portfolio/actions.ts`) that POSTs via
  `authedFetch("/portfolio/snapshots", { method: "POST" })`, then `revalidatePath`. Add a
  "History" link.
- `apps/web/app/portfolio/history/page.tsx` — server component using `authedFetch` to list
  snapshot dates + per-currency `total_value`.
- `apps/web/app/portfolio/history/[date]/page.tsx` — that day's positions table + currency totals.
- Plain tables only. Reuse the existing `fmtMoney`/`fmtNum` helpers from the portfolio page.

---

## Part D — Tests (backend, mocked — no broker/DB/network)
- **Normalisation** from a crafted `PortfolioResponse` (multi-currency, cash, one OK + one failed
  broker, a position with null `market_value`): row counts, cash rows, `partial_failure` +
  `broker_status_json`, per-currency totals, completeness flags, `cost_basis` only when
  `average_cost` present.
- **Allocation** per currency sums to ≈100% when all values present; null + incomplete flag when one missing.
- **Idempotency:** re-run same date → upsert (assert RPC payload via a fake supabase client; no duplicate).
- **Route auth:** snapshot endpoints → 401 without token, 403 for non-owner (use `mint_test_token` / `auth_header`).
- **Missing fields** handled safely (nulls).
- **Migration constraints** noted as **manual** (pytest has no live Postgres): unique, cascade,
  RPC service-role-only.

---

## Part E — Docs to update
- `docs/roadmap.md` — Phase 14.5 (goal, schema, per-currency/no-FX, idempotency, "relational stays
  source of truth; vector later").
- `docs/architecture.md` + `docs/data-model.md` — the three tables, the snapshot flow, and that
  snapshots are observational (not pipeline captures).
- `services/api/README.md` — migration `0009`, new endpoints, test count.
- Explain: why daily atomic snapshots exist; "normalised snapshot" = atomic per-asset rows (not a
  blob); how it differs from live holdings (immutable point-in-time history); how it seeds future
  LLM memory **without** building the vector DB now.

---

## Verification
```
cd services/api && .venv/Scripts/pytest -q
cd apps/web && npm run lint && npx tsc --noEmit && npm run build
git diff --check
```
Manual: apply `0009`; `POST /portfolio/snapshots`; re-POST same day → exactly one snapshot; `GET
/portfolio/snapshots/{today}` shows positions + per-currency totals; allocation per currency
≈100%; `/portfolio/history` renders.

---

## Do NOT touch
The auth/`require_user` logic, the read-only broker adapters, the capture→inbox→confirm pipeline,
or any existing migration. No FX, vector, embeddings, cron, or multi-user.

## Acceptance criteria
Migration creates 3 tables + RPC with RLS and service-role-only grants; `POST
/portfolio/snapshots` idempotent per day; positions are normalised atomic rows incl. cash;
per-currency allocation ≈100%; snapshot endpoints enforce auth + owner gate; tests green;
lint/tsc/build clean; docs updated.
