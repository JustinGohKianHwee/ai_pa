# Phase 17 — Food upgrade: calories, macros & photo input (plan for Codex execution)

> **Workflow:** Claude Code authored this plan; **Codex executes it**. Do not make
> architectural decisions — if anything is ambiguous, stop and ask. Recommended Codex
> settings: **model 5.5, effort high** (touches the capture pipeline, adds a vision service +
> storage, a migration with a confirm-RPC edit, frontend, and tests).

## Context
The food module currently logs `description` + `meal_type` + `logged_at` only. Phase 17 adds
**calorie/macro estimation** and **photo capture**: you send a food photo to the Telegram bot,
a vision model estimates the dish + nutrition, it flows through the **existing review pipeline**
(you confirm/correct the editable estimate), and it lands in an extended `food_logs`. Text food
captures also get estimates. This is a showcase of the capture→review→confirm pipeline + the
broker-free multimodal feature.

### Confirmed decisions (do not revisit)
- **Vision model:** OpenAI **`gpt-4o-mini`** (image input) — same client as the text classifier.
- **Photos stored** in a **private, owner-scoped Supabase Storage bucket**; shown via short-lived
  signed URLs the backend generates.
- **Estimates for photos AND text** — every food log carries calories + macros (editable in review).
- **Food-only with a "not food" escape** — if the model says a photo isn't food, mark the item
  `needs_manual_classification` (no fabricated meal). No receipt/finance routing in this phase.
- **Pipeline unchanged:** photo → `capture_event` → `inbox_item` (review gate) → confirm RPC →
  `food_logs`. Estimates are never auto-confirmed.

## Part A — Migration `supabase/migrations/0012_food_nutrition.sql`
- **`food_logs`** — add `calories numeric`, `protein_g numeric`, `carbs_g numeric`,
  `fat_g numeric`, `image_path text` (Storage object path; null for text logs). All nullable
  (estimates may be missing). `owner_id` already present (0010); RLS already enabled (0008).
- **`capture_events`** — add `image_path text` (the raw photo's Storage path, parallel to the
  existing `audio_file_id` for voice). The photo is the immutable raw capture.
- **`CREATE OR REPLACE confirm_food_item(uuid, timestamptz)`** — preserve the existing logic
  *exactly* (inspect `0006_food_logs.sql` and the 0011 memory-event addition), and additionally:
  - insert `calories`, `protein_g`, `carbs_g`, `fat_g` read from `v_item.structured_json`
    (e.g. `(v_item.structured_json->>'calories')::numeric`);
  - insert `image_path` read from the linked capture event
    (`select image_path from capture_events where id = v_item.capture_event_id`);
  - keep the atomic `memory_events` `confirmed` write from 0011 (optionally include `calories`
    in the compact payload).
  - Re-assert `revoke … from public, anon, authenticated; grant execute … to service_role;`.
- Update the README migration list to `0012`. **Applied manually by the user.**

## Part B — Supabase Storage (manual + code)
- **Manual (user):** create a **private** bucket named `food-photos` in Supabase Storage (not
  public). The backend uses the service-role key, so it can read/write; anon is denied. Document
  this as a prerequisite.
- **Code:** a small `app/services/storage.py`:
  - `upload_food_photo(image_bytes, object_path) -> str` — upload to `food-photos` via the
    Supabase client, return the stored path.
  - `signed_food_photo_url(object_path, expires_in=600) -> str | None` — create a short-lived
    signed URL for display.

## Part C — Vision food classifier (`app/services/food_vision.py`, new)
- `classify_food_image(image_bytes: bytes, caption: str | None) -> FoodImageResult` using
  `AsyncOpenAI` `gpt-4o-mini` with an image content part (base64 data URL) + a prompt that asks
  for strict JSON: `{ is_food: bool, description: str, meal_type: breakfast|lunch|dinner|snack|null,
  calories: float|null, protein_g, carbs_g, fat_g, confidence: 0..1 }`. Use the photo caption as
  extra context when present.
- Mirror the text classifier's structure: a Pydantic result model with validation, a
  `FoodVisionError` / `FoodVisionValidationError` hierarchy, and a **no-key fallback** (return
  `is_food=false`/low-confidence so the item goes to `needs_manual`, never a fabricated meal).
- `is_food=false` → caller marks the inbox item `needs_manual_classification`.

## Part D — Text classifier (extend `app/services/classifier.py`)
- Extend `FoodStructuredJson` with optional `calories`, `protein_g`, `carbs_g`, `fat_g`
  (`Optional[float]`, finite-and-non-negative validators like the finance `amount` check).
- Update the food line in `SYSTEM_PROMPT` to also estimate calories + macros from the text
  description. Keep `extra="forbid"`; `image_path` is **not** in structured_json (it lives on the
  capture event).

## Part E — Telegram webhook (extend `app/routes/telegram.py`)
- Add models: `TelegramPhotoSize` (`file_id`, `file_unique_id`, `width`, `height`, `file_size`)
  and `photo: Optional[list[TelegramPhotoSize]]` + `caption: Optional[str]` on `TelegramMessage`.
  (Telegram sends `photo` as an array of sizes — pick the **largest** by `file_size`/area.)
- Dispatch: after the text/voice checks, if `msg.photo` → `_capture_photo(...)`.
- `_capture_photo` (mirror `_capture_voice`'s structure + duplicate/recovery handling, source
  `telegram_photo`):
  1. dedupe on `(telegram_photo, chat:message_id)`;
  2. insert `capture_event` (`source=telegram_photo`, `processing_status=received`,
     metadata incl. caption);
  3. download the largest photo via `getFile` + file download (reuse the voice download pattern;
     never log the token-bearing URL); enforce a sane max size;
  4. `upload_food_photo(...)` → set `capture_events.image_path`;
  5. insert the `inbox_item` stub (`item_type=unknown`, title "Food photo", pending);
  6. `classify_food_image(...)`:
     - `is_food` → update inbox item to `item_type=food`, `structured_json` = {description,
       meal_type, calories, macros}, `confidence`, `review_status=pending`; capture
       `processing_status=classified`; write an `agent_runs` row (`agent_name=food_vision`,
       `model=gpt-4o-mini`).
     - not food / error / no key → `_mark_needs_manual`, `processing_status=classification_failed`,
       `agent_runs` error row.
  7. best-effort "✓ Captured" reply.
- Reuse the existing recovery/`_insert_recovery_inbox` and audit patterns. Independent DB writes
  as elsewhere.

## Part F — Read APIs (extend `app/routes/food.py`)
- `GET /food_logs?date=today` response: add per-log `calories`, `protein_g`, `carbs_g`, `fat_g`,
  and an `image_url` (signed URL from `image_path`, or null), plus a `totals` object summing
  calories + macros for the returned set.
- The inbox read (`GET /inbox`) should expose a signed `image_url` for food items that have a
  capture-event `image_path`, so the review card can show the photo. (Add the capture-event
  `image_path` to the inbox query/serialization and sign it.)

## Part G — Frontend
- **Inbox review card** (`app/inbox/InboxCard.tsx`): if the item is food and has an `image_url`,
  show the photo thumbnail; surface calories/macros (they're already editable via the
  structured-JSON editor — keep that; a friendly read-out of the numbers is a plus).
- **Food page** (`app/food/page.tsx`): show a **daily totals** header (calories + macros, tabular)
  and per-log calories/macros + image thumbnail, in the cockpit style.
- **Dashboard food tile** (`app/page.tsx`): show today's **total calories** (now available)
  instead of just the meal count.
- **Types** (`app/food/types.ts`, inbox types): add the nutrition fields, `image_url`, and the
  `totals` shape.

## Part H — Tests (backend, mocked — no network/storage)
- `food_vision`: mocked OpenAI image call → food estimate parsed; `is_food=false` path; no-key
  fallback (→ not food); malformed/invalid output → validation error.
- `classifier`: `FoodStructuredJson` accepts calories/macros and rejects negative/NaN; food
  classification round-trips the new fields.
- webhook photo path: capture + inbox created; storage upload + vision mocked; food item
  populated; not-food → needs_manual; duplicate/recovery handled; token never logged.
- `food` route: nutrition + signed `image_url` + `totals` shaped correctly (mock supabase +
  storage); auth (401/403) via `mint_test_token`.
- Confirm-RPC nutrition/image behavior is **manual** (pytest has no live Postgres) — note it.

## Part I — Docs
`docs/roadmap.md` (Phase 17), `docs/data-model.md` (food_logs new columns, `capture_events.image_path`,
the `food-photos` bucket), `docs/architecture.md` (photo capture + vision flow through the
pipeline), `services/api/README.md` (migration 0012, bucket prerequisite, vision model, test count).

## Verification
```
cd services/api && .venv/Scripts/pytest -q
cd apps/web && npm run lint && npx tsc --noEmit && npm run build
git diff --check
```
Manual (after applying 0012 + creating the `food-photos` bucket, locally — the Tiger key isn't
needed, but the OPENAI_API_KEY is): send a food photo to the bot → inbox shows the image +
estimated calories/macros → edit if needed → confirm → food page shows the log with nutrition +
daily totals + thumbnail; dashboard food tile shows today's calories. Send a non-food photo →
it lands as `needs_manual`, no invented meal.

## Out of scope
Receipt→finance routing (the "vision routes the photo" option — a later phase), barcode scanning,
calorie goals/targets, editing logs after confirm, multi-photo meals, public image URLs.

## Security notes (carry into the Phase 22 review)
- Bucket is **private**; images are served only via short-lived signed URLs minted by the
  authed backend. No public object URLs.
- Photos are sent to **OpenAI** for analysis — a privacy consideration worth noting (OpenAI's
  API data is not used for training per their API terms, but the user should be aware their food
  images leave the system to the model provider).
- The Telegram file-download URL embeds the bot token — never log it (existing pattern).
- Storage RLS denies anon/authenticated; the service-role backend is the only reader/writer.

---

## Prompt to Codex: Implement Phase 17

> **Model: 5.5 · Effort: high.** Implement **Phase 17 — food calories/macros + photo input** per
> `docs/phase-17-plan.md`. Do not make architectural decisions; if a confirm-RPC body or capture
> flow is unclear, stop and ask. **Scope:** photo capture via Telegram → `gpt-4o-mini` vision
> estimate → review pipeline → extended `food_logs`; text food also gets estimates; photos stored
> in a private Supabase Storage bucket; food-only with a "not food" → needs-manual escape.
> **No receipt/finance routing, no goals, no barcode, no public URLs.**
>
> **Inspect first:** `app/routes/telegram.py` (capture + voice-download + recovery patterns),
> `app/services/classifier.py` (FoodStructuredJson + prompt), `app/services/transcriber.py`
> (OpenAI client + Telegram file download), `supabase/migrations/0006_food_logs.sql` +
> `0011_memory_events.sql` (the `confirm_food_item` body to extend), `app/routes/food.py`,
> `app/db/supabase_client.py`, `apps/web/app/food/*`, `apps/web/app/inbox/InboxCard.tsx`,
> `apps/web/app/page.tsx`.
>
> Implement Parts A–I exactly as specified. **Migration 0012 and the `food-photos` bucket are
> applied manually by the user — do not run them.** Preserve `confirm_food_item`'s existing
> atomicity/idempotency and the 0011 memory-event write; the new columns are additive.
>
> **Run:** `pytest -q` (all green), `npm run lint && npx tsc --noEmit && npm run build`,
> `git diff --check`. Report results + the manual steps.
>
> **Do NOT touch:** auth/`require_user`, RLS, the broker adapters/portfolio, or unrelated
> migrations.
>
> **Acceptance criteria:** a food photo creates a pending food inbox item with the image + an
> editable calorie/macro estimate; confirming writes nutrition + `image_path` into `food_logs`
> atomically (+ a memory event); text food also carries estimates; a non-food photo becomes
> `needs_manual` with no fabricated meal; the food page shows daily totals + thumbnails; the
> dashboard food tile shows today's calories; storage bucket is private with signed-URL reads;
> tests + lint/tsc/build green.
