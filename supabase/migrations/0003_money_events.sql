-- ============================================================================
-- Migration 0003 — Finance domain module (Phase 9)
-- ============================================================================
-- The second domain table, following the Phase 8 tasks pattern exactly.
--
-- Pipeline reminder:
--     capture → classify/extract → pending inbox → review → atomic confirm + domain
--
-- Phase 9 adds:
--   1. money_events           — confirmed finance EXPENSES, one per source inbox_item
--   2. confirm_finance_item() — RPC that, in ONE transaction, creates exactly one
--                               money_event and flips the linked inbox_item to confirmed
--
-- Income decision (Phase 9): direction is CHECK-constrained to expense|income to match
-- docs/data-model.md and avoid a future widen-migration, but Phase 9 only ever CREATES
-- expense rows. confirm_finance_item hard-requires direction='expense'. Finance items with
-- direction='income' are confirmed status-only by the backend (Phase 7 path) and create no
-- money_event — income's module does not exist yet, so (like pre-Phase-8 task items) they
-- are not backfilled when income support later lands.
--
-- Invariants this migration preserves:
--   * One inbox_item produces at most one money_event (UNIQUE inbox_item_id).
--   * A money_event and its inbox_item's confirmed state are written together or not at
--     all (single-statement PL/pgSQL function = single transaction).
--   * money_events are immutable in Phase 9 (no edit/delete) → no updated_at/trigger.
--
-- NOT in this migration (deferred by design):
--   * Other domain tables (food_logs, calendar_intents, ...) — per-module, later.
--   * Row Level Security / auth — Phase 15. No user_id column yet (single-user).
--   * Income workflow/UI, net worth, budgets, recurring — out of Phase 9 scope.
--
-- occurred_at is stored as TEXT (the AI's free-text date verbatim, e.g. "yesterday").
-- It is not parsed to a timestamptz; finance views order by created_at.
-- ============================================================================


-- ----------------------------------------------------------------------------
-- money_events — confirmed finance expenses
-- ----------------------------------------------------------------------------
create table if not exists money_events (
    id            uuid primary key default gen_random_uuid(),
    inbox_item_id uuid not null unique references inbox_items (id),
    amount        numeric not null check (amount > 0),
    currency      text not null,
    direction     text not null check (direction in ('expense', 'income')),
    merchant      text,
    category      text,
    occurred_at   text,
    notes         text,
    created_at    timestamptz not null default now()
);

comment on table  money_events is
    'Confirmed finance records. Exactly one row per source inbox_item (UNIQUE inbox_item_id). Written only by confirm_finance_item() in the same transaction that confirms the inbox_item. Phase 9 creates expense rows only.';
comment on column money_events.inbox_item_id is
    'The reviewed inbox_item this event was confirmed from. UNIQUE — one event per item.';
comment on column money_events.amount is
    'Positive amount (CHECK amount > 0). Sourced from FinanceStructuredJson.amount.';
comment on column money_events.currency is
    'ISO-ish currency code as classified (default SGD). Totals are never summed across currencies.';
comment on column money_events.direction is
    'expense or income. Phase 9 only ever inserts expense; income is reserved for a later phase.';
comment on column money_events.occurred_at is
    'Free-text date exactly as extracted by the AI (e.g. "yesterday"). Stored as text — not parsed in Phase 9.';


-- ----------------------------------------------------------------------------
-- Indexes
-- ----------------------------------------------------------------------------
-- The /finance view orders by created_at. UNIQUE on inbox_item_id already provides
-- an index for the confirmation lookup.
create index if not exists idx_money_events_created_at on money_events (created_at);


-- ----------------------------------------------------------------------------
-- confirm_finance_item — atomic confirmation RPC
-- ----------------------------------------------------------------------------
-- Creates exactly one expense money_event for a pending finance inbox_item and flips
-- that item to confirmed, in one transaction. Returns { inbox_item, money_event } JSON.
--
-- Atomicity: a PL/pgSQL function invoked as a single statement runs inside one
-- transaction. Any RAISE aborts and rolls back every write in the function.
--
-- Idempotency / concurrency: identical to confirm_task_item — UNIQUE (inbox_item_id)
-- plus SELECT ... FOR UPDATE serialise parallel confirms, so at most one money_event is
-- ever created. An already-confirmed item with an event returns the existing pair; an
-- item confirmed WITHOUT an event (Phase 7/8 legacy, or an income status-only confirm) is
-- NOT backfilled — the function raises.
-- ----------------------------------------------------------------------------
create or replace function confirm_finance_item(
    p_inbox_id uuid,
    p_expected_updated_at timestamptz default null
)
returns jsonb
language plpgsql
as $$
declare
    v_item  inbox_items%rowtype;
    v_event money_events%rowtype;
    v_direction text;
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
        select * into v_event from money_events where inbox_item_id = p_inbox_id;
        if found then
            return jsonb_build_object(
                'inbox_item', to_jsonb(v_item),
                'money_event', to_jsonb(v_event)
            );
        end if;
        -- Confirmed with no event (legacy, or an income status-only confirm) → no backfill.
        raise exception 'confirmed_without_money_event: %', p_inbox_id
            using errcode = 'P0003';
    end if;

    -- 4. Must be pending to proceed.
    if v_item.review_status <> 'pending' then
        raise exception 'inbox_item_not_pending: % (%)', p_inbox_id, v_item.review_status
            using errcode = 'P0004';
    end if;

    -- 5. Must be a finance item.
    if v_item.item_type <> 'finance' then
        raise exception 'inbox_item_not_finance: % (%)', p_inbox_id, v_item.item_type
            using errcode = 'P0005';
    end if;

    -- 6. Phase 9 supports expense confirmation only.
    v_direction := v_item.structured_json->>'direction';
    if v_direction is distinct from 'expense' then
        raise exception 'unsupported_finance_direction: %', v_direction
            using errcode = 'P0007';
    end if;

    -- 7. Concurrency guard: reject a confirm built on a stale read.
    if p_expected_updated_at is not null and v_item.updated_at <> p_expected_updated_at then
        raise exception 'inbox_item_stale: %', p_inbox_id
            using errcode = 'P0006';
    end if;

    -- 8. Create exactly one expense event. UNIQUE (inbox_item_id) backstops a race;
    --    CHECK (amount > 0) backstops a bad amount.
    insert into money_events (
        inbox_item_id, amount, currency, direction, merchant, category, occurred_at, notes
    )
    values (
        v_item.id,
        (v_item.structured_json->>'amount')::numeric,
        coalesce(nullif(v_item.structured_json->>'currency', ''), 'SGD'),
        'expense',
        nullif(v_item.structured_json->>'merchant', ''),
        nullif(v_item.structured_json->>'category', ''),
        nullif(v_item.structured_json->>'occurred_at', ''),
        nullif(v_item.structured_json->>'notes', '')
    )
    returning * into v_event;

    -- 9. Confirm the inbox item using database UTC time.
    update inbox_items
       set review_status = 'confirmed',
           reviewed_at   = now()
     where id = p_inbox_id
    returning * into v_item;

    -- 10. Return both records.
    return jsonb_build_object(
        'inbox_item', to_jsonb(v_item),
        'money_event', to_jsonb(v_event)
    );
end;
$$;

-- RPC is backend/service-role only — never callable from the browser.
revoke all on function confirm_finance_item(uuid, timestamptz) from public;
revoke all on function confirm_finance_item(uuid, timestamptz) from anon;
revoke all on function confirm_finance_item(uuid, timestamptz) from authenticated;
grant execute on function confirm_finance_item(uuid, timestamptz) to service_role;
