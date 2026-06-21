-- ============================================================================
-- Migration 0006 — Food logs domain module (Phase 11)
-- ============================================================================
-- The third domain table, following the Phase 8 tasks and Phase 9 finance patterns.
--
-- Pipeline reminder:
--     capture → classify/extract → pending inbox → review → atomic confirm + domain
--
-- Phase 11 adds:
--   1. food_logs             — confirmed food records, one per source inbox_item
--   2. confirm_food_item()   — RPC that, in ONE transaction, creates exactly one
--                              food_log and flips the linked inbox_item to confirmed
--
-- "Today" filtering semantics:
--   The backend filter uses created_at (confirmation UTC timestamptz) with midnight
--   boundaries computed in the user's local timezone (USER_TIMEZONE env var). logged_at
--   is a verbatim display string only — NOT used for date filtering.
--   "Today" = the calendar day during which the food item was confirmed, in the user's
--   local timezone, not when the meal was eaten.
--
-- Invariants this migration preserves:
--   * One inbox_item produces at most one food_log (UNIQUE inbox_item_id).
--   * A food_log and its inbox_item's confirmed state are written together or not at
--     all (single-statement PL/pgSQL function = single transaction).
--   * food_logs are immutable in Phase 11 (no edit/delete) → no updated_at/trigger.
--
-- NOT in this migration (deferred by design):
--   * Row Level Security / auth — Phase 15. No user_id column yet (single-user).
--   * estimated_calories, estimated_protein_g — classifier doesn't extract these yet.
--   * notes — not in FoodStructuredJson; add when the classifier schema gains it.
--   * Other domain tables (calendar_intents, ...) — per-module, later phases.
-- ============================================================================


-- ----------------------------------------------------------------------------
-- food_logs — confirmed food records
-- ----------------------------------------------------------------------------
create table if not exists food_logs (
    id            uuid primary key default gen_random_uuid(),
    inbox_item_id uuid not null unique references inbox_items (id),
    description   text not null,
    meal_type     text check (meal_type is null
                              or meal_type in ('breakfast', 'lunch', 'dinner', 'snack')),
    logged_at     text,
    created_at    timestamptz not null default now()
);

comment on table food_logs is
    'Confirmed food records. Exactly one row per source inbox_item (UNIQUE inbox_item_id). Written only by confirm_food_item() in the same transaction that confirms the inbox_item. Immutable in Phase 11 — no updated_at.';
comment on column food_logs.inbox_item_id is
    'The reviewed inbox_item this log was confirmed from. UNIQUE — one log per item.';
comment on column food_logs.description is
    'Food description as extracted by the AI (e.g. "chicken rice"). Required — sourced from FoodStructuredJson.description.';
comment on column food_logs.meal_type is
    'breakfast, lunch, dinner, or snack. Nullable if the AI did not classify the meal.';
comment on column food_logs.logged_at is
    'Free-text time/date as extracted by the AI (e.g. "lunchtime", "today"). Stored as text — not parsed in Phase 11. NOT used for date filtering; filtering uses created_at.';


-- ----------------------------------------------------------------------------
-- Indexes
-- ----------------------------------------------------------------------------
-- The /food_logs view orders by created_at. UNIQUE on inbox_item_id already provides
-- an index for the confirmation lookup.
create index if not exists idx_food_logs_created_at on food_logs (created_at);


-- ----------------------------------------------------------------------------
-- confirm_food_item — atomic confirmation RPC
-- ----------------------------------------------------------------------------
-- Creates exactly one food_log for a pending food inbox_item and flips that item
-- to confirmed, in one transaction. Returns { inbox_item, food_log } JSON.
--
-- Atomicity: a PL/pgSQL function invoked as a single statement runs inside one
-- transaction. Any RAISE aborts and rolls back every write in the function.
--
-- Idempotency / concurrency: identical to confirm_task_item and confirm_finance_item —
-- UNIQUE (inbox_item_id) plus SELECT ... FOR UPDATE serialise parallel confirms, so at
-- most one food_log is ever created. An already-confirmed item with a log returns the
-- existing pair; an item confirmed WITHOUT a log (wrong path) is NOT backfilled —
-- the function raises.
-- ----------------------------------------------------------------------------
create or replace function confirm_food_item(
    p_inbox_id uuid,
    p_expected_updated_at timestamptz default null
)
returns jsonb
language plpgsql
as $$
declare
    v_item inbox_items%rowtype;
    v_log  food_logs%rowtype;
begin
    -- 1. Lock the inbox row for the duration of the transaction.
    select * into v_item from inbox_items where id = p_inbox_id for update;

    -- 2. Must exist.
    if not found then
        raise exception 'inbox_item_not_found: %', p_inbox_id
            using errcode = 'P0002';
    end if;

    -- 3. Idempotency: already confirmed.
    if v_item.review_status = 'confirmed' then
        select * into v_log from food_logs where inbox_item_id = p_inbox_id;
        if found then
            return jsonb_build_object(
                'inbox_item', to_jsonb(v_item),
                'food_log',   to_jsonb(v_log)
            );
        end if;
        -- Confirmed with no food_log (legacy path, or wrong item type confirmed before
        -- Phase 11) → no backfill.
        raise exception 'confirmed_without_food_log: %', p_inbox_id
            using errcode = 'P0003';
    end if;

    -- 4. Must be pending to proceed.
    if v_item.review_status <> 'pending' then
        raise exception 'inbox_item_not_pending: % (%)', p_inbox_id, v_item.review_status
            using errcode = 'P0004';
    end if;

    -- 5. Must be a food item.
    if v_item.item_type <> 'food' then
        raise exception 'inbox_item_not_food: % (%)', p_inbox_id, v_item.item_type
            using errcode = 'P0005';
    end if;

    -- 6. Concurrency guard: reject a confirm built on a stale read.
    if p_expected_updated_at is not null and v_item.updated_at <> p_expected_updated_at then
        raise exception 'inbox_item_stale: %', p_inbox_id
            using errcode = 'P0006';
    end if;

    -- 7. Create exactly one food log. UNIQUE (inbox_item_id) backstops any race not caught
    --    by the FOR UPDATE above.
    insert into food_logs (inbox_item_id, description, meal_type, logged_at)
    values (
        v_item.id,
        v_item.structured_json->>'description',
        nullif(v_item.structured_json->>'meal_type', ''),
        nullif(v_item.structured_json->>'logged_at', '')
    )
    returning * into v_log;

    -- 8. Confirm the inbox item using database UTC time.
    update inbox_items
       set review_status = 'confirmed',
           reviewed_at   = now()
     where id = p_inbox_id
    returning * into v_item;

    -- 9. Return both records.
    return jsonb_build_object(
        'inbox_item', to_jsonb(v_item),
        'food_log',   to_jsonb(v_log)
    );
end;
$$;

-- RPC is backend/service-role only — never callable from the browser.
revoke all on function confirm_food_item(uuid, timestamptz) from public;
revoke all on function confirm_food_item(uuid, timestamptz) from anon;
revoke all on function confirm_food_item(uuid, timestamptz) from authenticated;
grant execute on function confirm_food_item(uuid, timestamptz) to service_role;
