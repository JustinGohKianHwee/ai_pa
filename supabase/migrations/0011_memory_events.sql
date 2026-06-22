-- Replace <OWNER_USER_ID> with your Supabase owner UUID before running.
-- Phase 15b: append-only memory-ready events written atomically by existing RPCs.

create table if not exists memory_events (
    id uuid primary key default gen_random_uuid(),
    owner_id text not null default '<OWNER_USER_ID>',
    occurred_at timestamptz not null default now(),
    domain text not null,
    event_type text not null,
    payload_json jsonb not null default '{}'::jsonb,
    source_table text not null,
    source_id uuid,
    created_at timestamptz not null default now()
);

create index if not exists idx_memory_events_owner_occurred
    on memory_events (owner_id, occurred_at desc);
create index if not exists idx_memory_events_source
    on memory_events (source_table, source_id);

alter table memory_events enable row level security;
alter table memory_events force row level security;
revoke all on table memory_events from anon, authenticated;


-- Preserve confirm_task_item(uuid, timestamptz); add one event after a new confirmation.
create or replace function confirm_task_item(
    p_inbox_id uuid,
    p_expected_updated_at timestamptz default null
)
returns jsonb
language plpgsql
as $$
declare
    v_item inbox_items%rowtype;
    v_task tasks%rowtype;
begin
    select * into v_item from inbox_items where id = p_inbox_id for update;

    if not found then
        raise exception 'inbox_item_not_found: %', p_inbox_id
            using errcode = 'P0002';
    end if;

    if v_item.review_status = 'confirmed' then
        select * into v_task from tasks where inbox_item_id = p_inbox_id;
        if found then
            return jsonb_build_object(
                'inbox_item', to_jsonb(v_item),
                'task', to_jsonb(v_task)
            );
        end if;
        raise exception 'confirmed_without_task: %', p_inbox_id
            using errcode = 'P0003';
    end if;

    if v_item.review_status <> 'pending' then
        raise exception 'inbox_item_not_pending: % (%)', p_inbox_id, v_item.review_status
            using errcode = 'P0004';
    end if;

    if v_item.item_type <> 'task' then
        raise exception 'inbox_item_not_task: % (%)', p_inbox_id, v_item.item_type
            using errcode = 'P0005';
    end if;

    if p_expected_updated_at is not null and v_item.updated_at <> p_expected_updated_at then
        raise exception 'inbox_item_stale: %', p_inbox_id
            using errcode = 'P0006';
    end if;

    insert into tasks (inbox_item_id, title, urgency, due_date, notes)
    values (
        v_item.id,
        v_item.title,
        nullif(v_item.structured_json->>'urgency', ''),
        nullif(v_item.structured_json->>'due_date', ''),
        nullif(v_item.structured_json->>'notes', '')
    )
    returning * into v_task;

    update inbox_items
       set review_status = 'confirmed',
           reviewed_at   = now()
     where id = p_inbox_id
    returning * into v_item;

    insert into memory_events (
        domain, event_type, payload_json, source_table, source_id, occurred_at
    )
    values (
        'task',
        'confirmed',
        jsonb_build_object(
            'title', v_task.title,
            'status', v_task.status,
            'due_date', v_task.due_date
        ),
        'tasks',
        v_task.id,
        now()
    );

    return jsonb_build_object(
        'inbox_item', to_jsonb(v_item),
        'task', to_jsonb(v_task)
    );
end;
$$;


-- Preserve confirm_finance_item(uuid, timestamptz); add one event after a new confirmation.
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
    select * into v_item from inbox_items where id = p_inbox_id for update;

    if not found then
        raise exception 'inbox_item_not_found: %', p_inbox_id
            using errcode = 'P0002';
    end if;

    if v_item.review_status = 'confirmed' then
        select * into v_event from money_events where inbox_item_id = p_inbox_id;
        if found then
            return jsonb_build_object(
                'inbox_item', to_jsonb(v_item),
                'money_event', to_jsonb(v_event)
            );
        end if;
        raise exception 'confirmed_without_money_event: %', p_inbox_id
            using errcode = 'P0003';
    end if;

    if v_item.review_status <> 'pending' then
        raise exception 'inbox_item_not_pending: % (%)', p_inbox_id, v_item.review_status
            using errcode = 'P0004';
    end if;

    if v_item.item_type <> 'finance' then
        raise exception 'inbox_item_not_finance: % (%)', p_inbox_id, v_item.item_type
            using errcode = 'P0005';
    end if;

    v_direction := v_item.structured_json->>'direction';
    if v_direction is distinct from 'expense' then
        raise exception 'unsupported_finance_direction: %', v_direction
            using errcode = 'P0007';
    end if;

    if p_expected_updated_at is not null and v_item.updated_at <> p_expected_updated_at then
        raise exception 'inbox_item_stale: %', p_inbox_id
            using errcode = 'P0006';
    end if;

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

    update inbox_items
       set review_status = 'confirmed',
           reviewed_at   = now()
     where id = p_inbox_id
    returning * into v_item;

    insert into memory_events (
        domain, event_type, payload_json, source_table, source_id, occurred_at
    )
    values (
        'money',
        'confirmed',
        jsonb_build_object(
            'amount', v_event.amount,
            'currency', v_event.currency,
            'merchant', v_event.merchant,
            'direction', v_event.direction
        ),
        'money_events',
        v_event.id,
        now()
    );

    return jsonb_build_object(
        'inbox_item', to_jsonb(v_item),
        'money_event', to_jsonb(v_event)
    );
end;
$$;


-- Preserve confirm_food_item(uuid, timestamptz); add one event after a new confirmation.
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
    select * into v_item from inbox_items where id = p_inbox_id for update;

    if not found then
        raise exception 'inbox_item_not_found: %', p_inbox_id
            using errcode = 'P0002';
    end if;

    if v_item.review_status = 'confirmed' then
        select * into v_log from food_logs where inbox_item_id = p_inbox_id;
        if found then
            return jsonb_build_object(
                'inbox_item', to_jsonb(v_item),
                'food_log',   to_jsonb(v_log)
            );
        end if;
        raise exception 'confirmed_without_food_log: %', p_inbox_id
            using errcode = 'P0003';
    end if;

    if v_item.review_status <> 'pending' then
        raise exception 'inbox_item_not_pending: % (%)', p_inbox_id, v_item.review_status
            using errcode = 'P0004';
    end if;

    if v_item.item_type <> 'food' then
        raise exception 'inbox_item_not_food: % (%)', p_inbox_id, v_item.item_type
            using errcode = 'P0005';
    end if;

    if p_expected_updated_at is not null and v_item.updated_at <> p_expected_updated_at then
        raise exception 'inbox_item_stale: %', p_inbox_id
            using errcode = 'P0006';
    end if;

    insert into food_logs (inbox_item_id, description, meal_type, logged_at)
    values (
        v_item.id,
        v_item.structured_json->>'description',
        nullif(v_item.structured_json->>'meal_type', ''),
        nullif(v_item.structured_json->>'logged_at', '')
    )
    returning * into v_log;

    update inbox_items
       set review_status = 'confirmed',
           reviewed_at   = now()
     where id = p_inbox_id
    returning * into v_item;

    insert into memory_events (
        domain, event_type, payload_json, source_table, source_id, occurred_at
    )
    values (
        'food',
        'confirmed',
        jsonb_build_object(
            'description', v_log.description,
            'meal_type', v_log.meal_type,
            'logged_at', v_log.logged_at
        ),
        'food_logs',
        v_log.id,
        now()
    );

    return jsonb_build_object(
        'inbox_item', to_jsonb(v_item),
        'food_log',   to_jsonb(v_log)
    );
end;
$$;


-- Preserve confirm_calendar_item(uuid, timestamptz); add one event after a new confirmation.
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
    select * into v_item from inbox_items where id = p_inbox_id for update;

    if not found then
        raise exception 'inbox_item_not_found: %', p_inbox_id
            using errcode = 'P0002';
    end if;

    if v_item.review_status = 'confirmed' then
        select * into v_intent from calendar_intents where inbox_item_id = p_inbox_id;
        if found then
            return jsonb_build_object(
                'inbox_item',      to_jsonb(v_item),
                'calendar_intent', to_jsonb(v_intent)
            );
        end if;
        raise exception 'confirmed_without_calendar_intent: %', p_inbox_id
            using errcode = 'P0003';
    end if;

    if v_item.review_status <> 'pending' then
        raise exception 'inbox_item_not_pending: % (%)', p_inbox_id, v_item.review_status
            using errcode = 'P0004';
    end if;

    if v_item.item_type <> 'calendar' then
        raise exception 'inbox_item_not_calendar: % (%)', p_inbox_id, v_item.item_type
            using errcode = 'P0005';
    end if;

    if p_expected_updated_at is not null and v_item.updated_at <> p_expected_updated_at then
        raise exception 'inbox_item_stale: %', p_inbox_id
            using errcode = 'P0006';
    end if;

    insert into calendar_intents (inbox_item_id, title, proposed_datetime, location, notes)
    values (
        v_item.id,
        v_item.structured_json->>'title',
        nullif(v_item.structured_json->>'proposed_datetime', ''),
        nullif(v_item.structured_json->>'location', ''),
        nullif(v_item.structured_json->>'notes', '')
    )
    returning * into v_intent;

    update inbox_items
       set review_status = 'confirmed',
           reviewed_at   = now()
     where id = p_inbox_id
    returning * into v_item;

    insert into memory_events (
        domain, event_type, payload_json, source_table, source_id, occurred_at
    )
    values (
        'calendar',
        'confirmed',
        jsonb_build_object(
            'title', v_intent.title,
            'proposed_datetime', v_intent.proposed_datetime,
            'location', v_intent.location
        ),
        'calendar_intents',
        v_intent.id,
        now()
    );

    return jsonb_build_object(
        'inbox_item',      to_jsonb(v_item),
        'calendar_intent', to_jsonb(v_intent)
    );
end;
$$;


-- Preserve create_portfolio_snapshot; replace its one event for the canonical snapshot id.
create or replace function create_portfolio_snapshot(
    p_owner_id text,
    p_snapshot_date date,
    p_generated_at timestamptz,
    p_source text,
    p_partial_failure boolean,
    p_broker_status jsonb,
    p_currency_totals jsonb,
    p_positions jsonb
)
returns uuid
language plpgsql
as $$
declare
    v_snapshot_id uuid;
begin
    insert into portfolio_snapshots (
        owner_id,
        snapshot_date,
        generated_at,
        source,
        partial_failure,
        broker_status_json
    )
    values (
        p_owner_id,
        p_snapshot_date,
        p_generated_at,
        p_source,
        p_partial_failure,
        coalesce(p_broker_status, '{}'::jsonb)
    )
    on conflict (owner_id, snapshot_date) do update
       set generated_at = excluded.generated_at,
           source = excluded.source,
           partial_failure = excluded.partial_failure,
           broker_status_json = excluded.broker_status_json
    returning id into v_snapshot_id;

    delete from portfolio_snapshot_currency_totals where snapshot_id = v_snapshot_id;
    delete from portfolio_snapshot_positions where snapshot_id = v_snapshot_id;

    insert into portfolio_snapshot_currency_totals (
        snapshot_id,
        owner_id,
        currency,
        market_value,
        cash_value,
        invested_value,
        total_value,
        market_value_complete,
        market_value_missing
    )
    select
        v_snapshot_id,
        p_owner_id,
        item.currency,
        item.market_value,
        item.cash_value,
        item.invested_value,
        item.total_value,
        item.market_value_complete,
        item.market_value_missing
    from jsonb_to_recordset(coalesce(p_currency_totals, '[]'::jsonb)) as item(
        currency text,
        market_value numeric,
        cash_value numeric,
        invested_value numeric,
        total_value numeric,
        market_value_complete boolean,
        market_value_missing int
    );

    insert into portfolio_snapshot_positions (
        snapshot_id,
        owner_id,
        broker,
        account_ref,
        stable_asset_id,
        asset_symbol,
        asset_name,
        asset_type,
        instrument_id,
        quantity,
        price,
        market_value,
        average_cost,
        cost_basis,
        unrealized_pnl,
        today_pnl,
        currency,
        allocation_pct,
        quote_status,
        metadata_json
    )
    select
        v_snapshot_id,
        p_owner_id,
        item.broker,
        item.account_ref,
        item.stable_asset_id,
        item.asset_symbol,
        item.asset_name,
        item.asset_type,
        item.instrument_id,
        item.quantity,
        item.price,
        item.market_value,
        item.average_cost,
        item.cost_basis,
        item.unrealized_pnl,
        item.today_pnl,
        item.currency,
        item.allocation_pct,
        item.quote_status,
        coalesce(item.metadata_json, '{}'::jsonb)
    from jsonb_to_recordset(coalesce(p_positions, '[]'::jsonb)) as item(
        broker text,
        account_ref text,
        stable_asset_id text,
        asset_symbol text,
        asset_name text,
        asset_type text,
        instrument_id text,
        quantity numeric,
        price numeric,
        market_value numeric,
        average_cost numeric,
        cost_basis numeric,
        unrealized_pnl numeric,
        today_pnl numeric,
        currency text,
        allocation_pct numeric,
        quote_status text,
        metadata_json jsonb
    );

    delete from memory_events
     where source_table = 'portfolio_snapshots'
       and source_id = v_snapshot_id;

    insert into memory_events (
        domain, event_type, payload_json, source_table, source_id, occurred_at
    )
    values (
        'portfolio_snapshot',
        'snapshot_created',
        jsonb_build_object(
            'snapshot_date', p_snapshot_date,
            'partial_failure', p_partial_failure,
            'currency_totals', p_currency_totals
        ),
        'portfolio_snapshots',
        v_snapshot_id,
        p_generated_at
    );

    return v_snapshot_id;
end;
$$;


-- Reassert backend/service-role-only execution after replacing the functions.
revoke all on function confirm_task_item(uuid, timestamptz) from public, anon, authenticated;
grant execute on function confirm_task_item(uuid, timestamptz) to service_role;

revoke all on function confirm_finance_item(uuid, timestamptz) from public, anon, authenticated;
grant execute on function confirm_finance_item(uuid, timestamptz) to service_role;

revoke all on function confirm_food_item(uuid, timestamptz) from public, anon, authenticated;
grant execute on function confirm_food_item(uuid, timestamptz) to service_role;

revoke all on function confirm_calendar_item(uuid, timestamptz) from public, anon, authenticated;
grant execute on function confirm_calendar_item(uuid, timestamptz) to service_role;

revoke all on function create_portfolio_snapshot(
    text, date, timestamptz, text, boolean, jsonb, jsonb, jsonb
) from public, anon, authenticated;
grant execute on function create_portfolio_snapshot(
    text, date, timestamptz, text, boolean, jsonb, jsonb, jsonb
) to service_role;
