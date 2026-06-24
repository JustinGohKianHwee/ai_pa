-- ============================================================================
-- Migration 0018 — Financial goal progress v1 (Phase 22b-2)
-- ============================================================================
-- Extends `goals` (Phase 20) with a numeric monetary target so a goal can be a
-- "financial goal" whose progress is measured deterministically, by currency.
--
-- A goal is a FINANCIAL goal iff target_value IS NOT NULL AND target_currency IS NOT NULL.
-- target_metric picks which deterministic base measures progress (different goals use
-- different bases): net_worth | liquid_cash | invested | broker_total. Null defaults to
-- net_worth at read time. Progress = base_value[target_currency] / target_value (no FX,
-- never cross-currency). No attribution, no activity linking, no projections.
--
-- This widens NO item_type (goals already allowed). It CREATE OR REPLACEs confirm_goal_item
-- to persist the new fields, preserving the Phase 20 behaviour + memory-event write exactly.
-- ============================================================================

alter table goals add column if not exists target_value numeric
    check (target_value is null or target_value >= 0);
alter table goals add column if not exists target_currency text;
alter table goals add column if not exists target_metric text
    check (target_metric is null
           or target_metric in ('net_worth', 'liquid_cash', 'invested', 'broker_total'));

comment on column goals.target_value is
    'Numeric monetary target. Set (with target_currency) makes this a financial goal. Nullable.';
comment on column goals.target_metric is
    'Which deterministic base measures progress: net_worth|liquid_cash|invested|broker_total. Null → net_worth.';


create or replace function confirm_goal_item(
    p_inbox_id uuid,
    p_expected_updated_at timestamptz default null
)
returns jsonb
language plpgsql
as $$
declare
    v_item inbox_items%rowtype;
    v_goal goals%rowtype;
begin
    select * into v_item from inbox_items where id = p_inbox_id for update;

    if not found then
        raise exception 'inbox_item_not_found: %', p_inbox_id using errcode = 'P0002';
    end if;

    if v_item.review_status = 'confirmed' then
        select * into v_goal from goals where inbox_item_id = p_inbox_id;
        if found then
            return jsonb_build_object('inbox_item', to_jsonb(v_item), 'goal', to_jsonb(v_goal));
        end if;
        raise exception 'confirmed_without_goal: %', p_inbox_id using errcode = 'P0003';
    end if;

    if v_item.review_status <> 'pending' then
        raise exception 'inbox_item_not_pending: % (%)', p_inbox_id, v_item.review_status
            using errcode = 'P0004';
    end if;

    if v_item.item_type <> 'goal' then
        raise exception 'inbox_item_not_goal: % (%)', p_inbox_id, v_item.item_type
            using errcode = 'P0005';
    end if;

    if p_expected_updated_at is not null and v_item.updated_at <> p_expected_updated_at then
        raise exception 'inbox_item_stale: %', p_inbox_id using errcode = 'P0006';
    end if;

    -- status defaults to 'active' (column default). Phase 22b-2 adds the numeric target fields.
    insert into goals (
        inbox_item_id, title, description, target, target_date,
        target_value, target_currency, target_metric
    )
    values (
        v_item.id,
        v_item.structured_json->>'title',
        nullif(v_item.structured_json->>'description', ''),
        nullif(v_item.structured_json->>'target', ''),
        nullif(v_item.structured_json->>'target_date', ''),
        (v_item.structured_json->>'target_value')::numeric,
        nullif(v_item.structured_json->>'target_currency', ''),
        nullif(v_item.structured_json->>'target_metric', '')
    )
    returning * into v_goal;

    update inbox_items
       set review_status = 'confirmed',
           reviewed_at   = now()
     where id = p_inbox_id
    returning * into v_item;

    insert into memory_events (
        domain, event_type, payload_json, source_table, source_id, occurred_at
    )
    values (
        'goal',
        'confirmed',
        jsonb_build_object(
            'title',           v_goal.title,
            'target',          v_goal.target,
            'target_date',     v_goal.target_date,
            'status',          v_goal.status,
            'target_value',    v_goal.target_value,
            'target_currency', v_goal.target_currency
        ),
        'goals',
        v_goal.id,
        now()
    );

    return jsonb_build_object('inbox_item', to_jsonb(v_item), 'goal', to_jsonb(v_goal));
end;
$$;

revoke all on function confirm_goal_item(uuid, timestamptz) from public, anon, authenticated;
grant execute on function confirm_goal_item(uuid, timestamptz) to service_role;
