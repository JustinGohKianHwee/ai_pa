# Phase 18 — Exercise / workouts module

**Owner:** Codex (execute) · Claude (plan + review). Codex is rate-limited until 2026-06-26;
this plan is ready for then. **Model/effort suggestion:** GPT-5.5 medium effort — this is a
well-trodden module pattern (mirror Phase 11/17 food), not novel architecture.

## Goal
Capture an exercise/workout (text or voice) → classify → review → confirm into a new
`exercise_logs` domain table, with a dedicated `/exercise` page and a dashboard tile. Strictly
the **standard module pattern** already used by tasks/finance/food/calendar. No new capture
surface, no auto-actions, review-first preserved.

## Definition of done
- "Ran 5k in 28 min this morning" → inbox item `item_type=exercise` with structured fields →
  confirm → one `exercise_logs` row → visible at `/exercise`.
- Confirm is atomic + idempotent (unique `inbox_item_id`) and writes exactly one `memory_events`
  `confirmed` row in the same transaction (mirror `confirm_food_item` in `0012`).
- `GET /exercise_logs` (+ `?date=today`) returns rows with daily totals; auth 401/403 enforced.
- Backend `pytest` green; frontend `lint` + `tsc --noEmit` + `build` clean.

## Build order

### 1. Migration `supabase/migrations/0013_exercise_logs.sql` (user applies manually)
Mirror `0012` structure exactly.
- `create table exercise_logs`:
  - `id uuid pk default gen_random_uuid()`
  - `inbox_item_id uuid not null unique references inbox_items(id)`
  - `owner_id` — **default-filled non-null**, same definition/pattern as the 0010 columns
    (copy how `food_logs.owner_id` is declared post-0010 so the default backfill applies).
  - `activity text not null` (e.g. "running", "gym - chest", "yoga")
  - `duration_min numeric` (nullable)
  - `distance_km numeric` (nullable)
  - `sets integer`, `reps integer` (nullable)
  - `intensity text` — nullable, free text ("easy"/"moderate"/"hard") — do **not** constrain
  - `calories numeric` (nullable; optional AI estimate, editable in review)
  - `logged_at text` (nullable; verbatim AI output, **not** parsed — same rule as food)
  - `notes text` (nullable)
  - `created_at timestamptz not null default now()`
- `create or replace function confirm_exercise_item(p_inbox_id uuid, p_expected_updated_at
  timestamptz default null) returns jsonb` — copy `confirm_food_item` from `0012` verbatim and
  adapt: guard `item_type <> 'exercise'` (errcode P0005 message `inbox_item_not_exercise`), the
  `confirmed_without_exercise_log` branch, insert the fields above from `structured_json`
  (numeric casts via `(structured_json->>'x')::numeric`, ints via `::integer`,
  `nullif(...,'')` for text), and append a `memory_events` row with `domain='exercise'`,
  `event_type='confirmed'`, `source_table='exercise_logs'`, payload
  `{activity, duration_min, distance_km, logged_at}`.
- `revoke all ... from public, anon, authenticated; grant execute ... to service_role;`
  (same two lines as 0012).

### 2. Classifier (`services/api/app/services/classifier.py`)
- Add `ExerciseStructuredJson` (mirror `FoodStructuredJson`): `activity: str`, optional
  `duration_min/distance_km/sets/reps/calories` (finite, ≥0 validators — reuse the food
  validator style), `intensity: Optional[str]`, `logged_at: Optional[str]`, `notes:
  Optional[str]`. `extra="ignore"`.
- Register `exercise` in the item-type union / dispatch the same way `food` is wired (match the
  existing structure — there is a per-type structured-model map; add the entry there).
- Update `SYSTEM_PROMPT`: add an `exercise` line instructing extraction of activity + the
  numeric fields when present, and a rough `calories` estimate (approximate, user will review).
  Keep the existing food/task/finance/calendar lines unchanged.

### 3. Read API `services/api/app/routes/exercise.py` (new; mirror `food.py`)
- `GET /exercise_logs` with optional `?date=today` using the **same** `USER_TIMEZONE`-aware
  `created_at` midnight-boundary logic as `food.py` (invalid `date=` → 422, no silent fallback).
- `ExerciseLogResponse` (all fields above) + an `ExerciseTotals` (sum `duration_min`,
  `distance_km`, `calories`) + `ExerciseLogsListResponse{items, totals}` — mirror the food
  totals shape added in Phase 17.
- `dependencies=[Depends(require_user)]` on the route (auth 401/403 like other read routes).
- Register the router in `app/main.py` next to the food router.

### 4. Frontend
- `apps/web/app/exercise/page.tsx` + `apps/web/app/exercise/types.ts` — mirror `app/food/page.tsx`:
  today's workouts (server component, `force-dynamic`), a totals header (duration / distance /
  calories, `.numeric` tabular), per-log detail. Reuse the existing UI kit + `lib/format.ts`.
- `apps/web/app/page.tsx` — add an "Exercise today" dashboard tile (duration or session count),
  mirroring the food calories tile. Use the same `authedFetch` server-side fetch pattern.
- Add `/exercise` to the nav rail (`components/NavRail.tsx`) with a lucide icon (e.g. `Dumbbell`).

### 5. Tests (`services/api/tests/test_exercise_logs.py`, mirror `test_food_logs.py`)
- Empty list returns `{items: [], totals: {...zeroed}}`.
- Rows map correctly; totals sum; `?date=today` filtering; invalid date → 422.
- Auth: 401 without token, 403 for non-owner (`mint_test_token` helper as in food tests).
- Classifier: `ExerciseStructuredJson` accepts valid, rejects negative/NaN numerics.
- Confirm-RPC nutrition/memory-event assertions are manual (DB), as with food.

## Reuse / integration notes (verified against current tree)
- Confirm-RPC template: `supabase/migrations/0012_food_nutrition.sql` lines 15–111 — copy
  wholesale, rename, swap fields. Preserve the `for update` lock, the four guards, the
  already-confirmed replay branch, and the `memory_events` insert.
- `owner_id` is default-filled by migration 0010 — inserts must **not** set it.
- Read-route template: `services/api/app/routes/food.py` (totals + `?date=today` + auth).
- Classifier extension template: `FoodStructuredJson` + the food `SYSTEM_PROMPT` line.
- Frontend templates: `app/food/page.tsx`, `app/food/types.ts`, the food dashboard tile in
  `app/page.tsx`.

## Verification
```
cd services/api && .venv/Scripts/pytest -q
cd apps/web && npm run lint && npx tsc --noEmit && npm run build
git diff --check
```
Manual (local): apply `0013`; send "did legs at the gym, 45 min" → inbox shows `exercise` with
editable fields → confirm → `/exercise` shows it + daily totals; dashboard tile updates.

## Out of scope (do NOT build)
Wearable/Strava/Apple Health import, GPS routes, workout templates/programs, PR tracking,
charts, editing logs after confirmation, calorie-burn science beyond a rough estimate, any
auto-action. Timeline/goals/attribution are later phases — do not anticipate them here.
