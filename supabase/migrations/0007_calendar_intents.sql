-- ============================================================================
-- Migration 0007 — Calendar intents domain module (Phase 12)
-- ============================================================================
-- The fourth domain table, following the Phase 8 tasks, Phase 9 finance, and
-- Phase 11 food patterns.
--
-- Pipeline reminder:
--     capture → classify/extract → pending inbox → review → atomic confirm + domain
--
-- Phase 12 adds:
--   1. calendar_intents       — confirmed calendar intentions, one per source inbox_item
--   2. confirm_calendar_item() — RPC that, in ONE transaction, creates exactly one
--                                calendar_intent and flips the linked inbox_item to confirmed
--
-- Key decisions (Phase 12):
--   * proposed_datetime is stored as TEXT — verbatim AI output, NOT parsed to a timestamp.
--     Same pattern as occurred_at (money_events) and logged_at (food_logs).
--   * No status column (draft/synced) — deferred until calendar sync is introduced.
--     A column frozen at 'draft' with no transition logic adds schema noise now.
--   * No user_id — single-user until Phase 15 auth/RLS.
--   * Display order: created_at DESC (confirmation time). Without a parsed datetime
--     there is no meaningful way to sort by event time.
--
-- Invariants this migration preserves:
--   * One inbox_item produces at most one calendar_intent (UNIQUE inbox_item_id).
--   * A calendar_intent and its inbox_item's confirmed state are written together or
--     not at all (single-statement PL/pgSQL function = single transaction).
--   * calendar_intents are immutable in Phase 12 — no updated_at/trigger.
-- ============================================================================


-- ----------------------------------------------------------------------------
-- calendar_intents — confirmed calendar intention records
-- ----------------------------------------------------------------------------
create table if not exists calendar_intents (
    id                uuid primary key default gen_random_uuid(),
    inbox_item_id     uuid not null unique references inbox_items (id),
    title             text not null,
    proposed_datetime text,
    location          text,
    notes             text,
    created_at        timestamptz not null default now()
);

comment on table calendar_intents is
    'Confirmed calendar intentions. Exactly one row per source inbox_item (UNIQUE inbox_item_id). Written only by confirm_calendar_item() in the same transaction that confirms the inbox_item. Immutable in Phase 12.';
comment on column calendar_intents.inbox_item_id is
    'The reviewed inbox_item this intent was confirmed from. UNIQUE — one intent per item.';
comment on column calendar_intents.title is
    'Event title as extracted by the AI. Required.';
comment on column calendar_intents.proposed_datetime is
    'Free-text proposed datetime as extracted by the AI (e.g. "next Friday 7pm"). Stored as text — NOT parsed in Phase 12. Display only.';
comment on column calendar_intents.location is
    'Optional location as extracted by the AI.';
comment on column calendar_intents.notes is
    'Optional notes as extracted by the AI.';


-- ----------------------------------------------------------------------------
-- Indexes
-- ----------------------------------------------------------------------------
create index if not exists idx_calendar_intents_created_at on calendar_intents (created_at);


-- ----------------------------------------------------------------------------
-- confirm_calendar_item — atomic confirmation RPC
-- ----------------------------------------------------------------------------
-- Creates exactly one calendar_intent for a pending calendar inbox_item and flips
-- that item to confirmed, in one transaction. Returns { inbox_item, calendar_intent } JSON.
--
-- Atomicity: a PL/pgSQL function invoked as a single statement runs inside one
-- transaction. Any RAISE aborts and rolls back every write in the function.
--
-- Idempotency / concurrency: identical to confirm_task_item, confirm_finance_item, and
-- confirm_food_item — UNIQUE (inbox_item_id) plus SELECT ... FOR UPDATE serialise
-- parallel confirms, so at most one calendar_intent is ever created.
-- ----------------------------------------------------------------------------
create or replace function confirm_calendar_item(
    p_inbox_id uuid,
    p_expected_updated_at timestamptz default null
)
returns jsonb
language plpgsql
as $$
declare
    v_item   inbox_items%rowtype;
    v_intent calendar_intents%rowtype;
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
        select * into v_intent from calendar_intents where inbox_item_id = p_inbox_id;
        if found then
            return jsonb_build_object(
                'inbox_item',      to_jsonb(v_item),
                'calendar_intent', to_jsonb(v_intent)
            );
        end if;
        -- Confirmed with no calendar_intent (legacy path, or wrong item type confirmed
        -- before Phase 12) → no backfill.
        raise exception 'confirmed_without_calendar_intent: %', p_inbox_id
            using errcode = 'P0003';
    end if;

    -- 4. Must be pending to proceed.
    if v_item.review_status <> 'pending' then
        raise exception 'inbox_item_not_pending: % (%)', p_inbox_id, v_item.review_status
            using errcode = 'P0004';
    end if;

    -- 5. Must be a calendar item.
    if v_item.item_type <> 'calendar' then
        raise exception 'inbox_item_not_calendar: % (%)', p_inbox_id, v_item.item_type
            using errcode = 'P0005';
    end if;

    -- 6. Concurrency guard: reject a confirm built on a stale read.
    if p_expected_updated_at is not null and v_item.updated_at <> p_expected_updated_at then
        raise exception 'inbox_item_stale: %', p_inbox_id
            using errcode = 'P0006';
    end if;

    -- 7. Create exactly one calendar intent. UNIQUE (inbox_item_id) backstops any race
    --    not caught by the FOR UPDATE above.
    insert into calendar_intents (inbox_item_id, title, proposed_datetime, location, notes)
    values (
        v_item.id,
        v_item.structured_json->>'title',
        nullif(v_item.structured_json->>'proposed_datetime', ''),
        nullif(v_item.structured_json->>'location', ''),
        nullif(v_item.structured_json->>'notes', '')
    )
    returning * into v_intent;

    -- 8. Confirm the inbox item using database UTC time.
    update inbox_items
       set review_status = 'confirmed',
           reviewed_at   = now()
     where id = p_inbox_id
    returning * into v_item;

    -- 9. Return both records.
    return jsonb_build_object(
        'inbox_item',      to_jsonb(v_item),
        'calendar_intent', to_jsonb(v_intent)
    );
end;
$$;

-- RPC is backend/service-role only — never callable from the browser.
revoke all on function confirm_calendar_item(uuid, timestamptz) from public;
revoke all on function confirm_calendar_item(uuid, timestamptz) from anon;
revoke all on function confirm_calendar_item(uuid, timestamptz) from authenticated;
grant execute on function confirm_calendar_item(uuid, timestamptz) to service_role;
