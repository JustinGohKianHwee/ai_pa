-- Replace <OWNER_USER_ID> with your Supabase owner UUID before running.
-- ============================================================================
-- Migration 0017 — Manual financial snapshots (Phase 22a)
-- ============================================================================
-- The reviewed manual input that feeds the deterministic Financial Intelligence
-- layer: a point-in-time statement of non-broker cash, recurring monthly income,
-- monthly investment contribution, and liabilities — by currency.
--
-- Pipeline reminder:
--     capture → classify/extract → pending inbox → review → atomic confirm + domain
--
-- Scope (locked, Phase 22a):
--   * One consolidated, IMMUTABLE snapshot per confirmation. Latest by created_at is
--     "current"; update by capturing a new one (no edit endpoint, no status).
--   * Amounts are stored per-currency as JSONB arrays of {currency, amount}. They are
--     NEVER summed across currencies anywhere.
--   * liquid_cash is NON-BROKER cash only (bank/CPF). Broker cash comes from portfolio
--     snapshots — keeping them separate avoids double counting in net worth.
--   * No bank API/auto-pull, no FX, no advice. Shape is mainly guarded by Pydantic in
--     the app; the CHECKs here only assert each column is a JSON array.
--
-- CRITICAL (Phase 18/20/21 lesson): widen inbox_items.item_type CHECK to include
-- 'financial_snapshot', or confirming/classifying these items fails with a postgrest
-- APIError. (tests/test_item_type_constraint.py guards this.)
-- ============================================================================


-- ----------------------------------------------------------------------------
-- 0. Widen inbox_items.item_type to allow 'financial_snapshot'
-- ----------------------------------------------------------------------------
alter table inbox_items drop constraint if exists inbox_items_item_type_check;

alter table inbox_items add constraint inbox_items_item_type_check
    check (item_type in (
        'task',
        'finance',
        'calendar',
        'food',
        'exercise',
        'habit',
        'goal',
        'decision',
        'financial_snapshot',
        'investment',
        'note',
        'journal',
        'unknown'
    ));


-- ----------------------------------------------------------------------------
-- 1. manual_financial_snapshots — reviewed point-in-time financial inputs
-- ----------------------------------------------------------------------------
create table if not exists manual_financial_snapshots (
    id                      uuid primary key default gen_random_uuid(),
    inbox_item_id           uuid not null unique references inbox_items (id),
    owner_id                text not null default 'd64140ca-fad6-4444-84f6-96b976d5f784',
    as_of                   text,
    monthly_income_json     jsonb not null default '[]'::jsonb,
    monthly_investment_json jsonb not null default '[]'::jsonb,
    liquid_cash_json        jsonb not null default '[]'::jsonb,
    liabilities_json        jsonb not null default '[]'::jsonb,
    notes                   text,
    created_at              timestamptz not null default now(),
    -- Basic shape guard only (Pydantic is the real validator): each column is a JSON array.
    constraint manual_financial_snapshots_arrays_check check (
        jsonb_typeof(monthly_income_json) = 'array'
        and jsonb_typeof(monthly_investment_json) = 'array'
        and jsonb_typeof(liquid_cash_json) = 'array'
        and jsonb_typeof(liabilities_json) = 'array'
    )
);

comment on table manual_financial_snapshots is
    'Reviewed manual financial inputs (cash/income/investment/liabilities by currency). One row per source inbox_item (UNIQUE inbox_item_id). Written only by confirm_financial_snapshot_item(). Immutable — latest by created_at is current; update by capturing a new snapshot.';
comment on column manual_financial_snapshots.liquid_cash_json is
    'NON-broker cash (bank/CPF) as JSON array of {currency, amount}. Broker cash comes from portfolio snapshots; keep separate to avoid double counting.';
comment on column manual_financial_snapshots.as_of is
    'Free-text "as of" date, verbatim from the AI (e.g. "today"). NOT parsed.';

create index if not exists idx_manual_financial_snapshots_created_at
    on manual_financial_snapshots (created_at);

alter table manual_financial_snapshots enable row level security;
alter table manual_financial_snapshots force row level security;
revoke all on table manual_financial_snapshots from anon, authenticated;


-- ----------------------------------------------------------------------------
-- 2. confirm_financial_snapshot_item — atomic confirmation RPC
-- ----------------------------------------------------------------------------
create or replace function confirm_financial_snapshot_item(
    p_inbox_id uuid,
    p_expected_updated_at timestamptz default null
)
returns jsonb
language plpgsql
as $$
declare
    v_item inbox_items%rowtype;
    v_snap manual_financial_snapshots%rowtype;
begin
    select * into v_item from inbox_items where id = p_inbox_id for update;

    if not found then
        raise exception 'inbox_item_not_found: %', p_inbox_id using errcode = 'P0002';
    end if;

    if v_item.review_status = 'confirmed' then
        select * into v_snap from manual_financial_snapshots where inbox_item_id = p_inbox_id;
        if found then
            return jsonb_build_object(
                'inbox_item',        to_jsonb(v_item),
                'financial_snapshot', to_jsonb(v_snap)
            );
        end if;
        raise exception 'confirmed_without_financial_snapshot: %', p_inbox_id using errcode = 'P0003';
    end if;

    if v_item.review_status <> 'pending' then
        raise exception 'inbox_item_not_pending: % (%)', p_inbox_id, v_item.review_status
            using errcode = 'P0004';
    end if;

    if v_item.item_type <> 'financial_snapshot' then
        raise exception 'inbox_item_not_financial_snapshot: % (%)', p_inbox_id, v_item.item_type
            using errcode = 'P0005';
    end if;

    if p_expected_updated_at is not null and v_item.updated_at <> p_expected_updated_at then
        raise exception 'inbox_item_stale: %', p_inbox_id using errcode = 'P0006';
    end if;

    insert into manual_financial_snapshots (
        inbox_item_id, as_of,
        monthly_income_json, monthly_investment_json, liquid_cash_json, liabilities_json,
        notes
    )
    values (
        v_item.id,
        nullif(v_item.structured_json->>'as_of', ''),
        coalesce(v_item.structured_json->'monthly_income', '[]'::jsonb),
        coalesce(v_item.structured_json->'monthly_investment', '[]'::jsonb),
        coalesce(v_item.structured_json->'liquid_cash', '[]'::jsonb),
        coalesce(v_item.structured_json->'liabilities', '[]'::jsonb),
        nullif(v_item.structured_json->>'notes', '')
    )
    returning * into v_snap;

    update inbox_items
       set review_status = 'confirmed',
           reviewed_at   = now()
     where id = p_inbox_id
    returning * into v_item;

    insert into memory_events (
        domain, event_type, payload_json, source_table, source_id, occurred_at
    )
    values (
        'financial_snapshot',
        'confirmed',
        jsonb_build_object('as_of', v_snap.as_of),
        'manual_financial_snapshots',
        v_snap.id,
        now()
    );

    return jsonb_build_object(
        'inbox_item',        to_jsonb(v_item),
        'financial_snapshot', to_jsonb(v_snap)
    );
end;
$$;


-- ----------------------------------------------------------------------------
-- 3. Grants — RPC is backend/service-role only
-- ----------------------------------------------------------------------------
revoke all on function confirm_financial_snapshot_item(uuid, timestamptz) from public, anon, authenticated;
grant execute on function confirm_financial_snapshot_item(uuid, timestamptz) to service_role;
