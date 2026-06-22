-- Phase 14.5: one canonical normalized portfolio snapshot per owner per local day.
-- Snapshots are observational broker facts, not inbox/domain confirmation records.

create table if not exists portfolio_snapshots (
    id uuid primary key default gen_random_uuid(),
    owner_id text not null,
    snapshot_date date not null,
    generated_at timestamptz not null,
    source text not null,
    partial_failure boolean not null default false,
    broker_status_json jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (owner_id, snapshot_date)
);

create table if not exists portfolio_snapshot_currency_totals (
    id uuid primary key default gen_random_uuid(),
    snapshot_id uuid not null references portfolio_snapshots(id) on delete cascade,
    owner_id text not null,
    currency text not null,
    market_value numeric not null default 0,
    cash_value numeric not null default 0,
    invested_value numeric not null default 0,
    total_value numeric not null default 0,
    market_value_complete boolean not null default true,
    market_value_missing int not null default 0,
    unique (snapshot_id, currency)
);

create table if not exists portfolio_snapshot_positions (
    id uuid primary key default gen_random_uuid(),
    snapshot_id uuid not null references portfolio_snapshots(id) on delete cascade,
    owner_id text not null,
    broker text not null,
    account_ref text not null,
    stable_asset_id text not null,
    asset_symbol text not null,
    asset_name text,
    asset_type text not null,
    instrument_id text,
    quantity numeric,
    price numeric,
    market_value numeric,
    average_cost numeric,
    cost_basis numeric,
    unrealized_pnl numeric,
    today_pnl numeric,
    currency text not null,
    allocation_pct numeric,
    quote_status text,
    metadata_json jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

drop trigger if exists trg_portfolio_snapshots_set_updated_at on portfolio_snapshots;
create trigger trg_portfolio_snapshots_set_updated_at
    before update on portfolio_snapshots
    for each row
    execute function set_updated_at();

alter table portfolio_snapshots enable row level security;
alter table portfolio_snapshots force row level security;
revoke all on table portfolio_snapshots from anon, authenticated;

alter table portfolio_snapshot_currency_totals enable row level security;
alter table portfolio_snapshot_currency_totals force row level security;
revoke all on table portfolio_snapshot_currency_totals from anon, authenticated;

alter table portfolio_snapshot_positions enable row level security;
alter table portfolio_snapshot_positions force row level security;
revoke all on table portfolio_snapshot_positions from anon, authenticated;

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

    return v_snapshot_id;
end;
$$;

revoke all on function create_portfolio_snapshot(
    text, date, timestamptz, text, boolean, jsonb, jsonb, jsonb
) from public, anon, authenticated;
grant execute on function create_portfolio_snapshot(
    text, date, timestamptz, text, boolean, jsonb, jsonb, jsonb
) to service_role;
