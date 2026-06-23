-- Replace <OWNER_USER_ID> with your Supabase owner UUID before running.
-- ============================================================================
-- Migration 0013 — Exercise / workout logs domain module (Phase 18)
-- ============================================================================
-- The fifth domain table, following the tasks/finance/food/calendar pattern and
-- the Phase 15b memory-event contract (one append-only memory_events row per
-- confirmation, written in the same transaction).
--
-- Pipeline reminder:
--     capture → classify/extract → pending inbox → review → atomic confirm + domain
--
-- Invariants preserved:
--   * One inbox_item produces at most one exercise_log (UNIQUE inbox_item_id).
--   * The exercise_log, the inbox confirmation, and the memory_event are written
--     together or not at all (single-statement PL/pgSQL function = one transaction).
--   * exercise_logs are immutable in Phase 18 (no edit/delete) → no updated_at.
--   * owner_id is default-filled (single-owner), matching migration 0010/0011.
--   * RLS is deny-by-default; only the service-role backend (BYPASSRLS) reads/writes.
--
-- "Today" filtering uses created_at with USER_TIMEZONE-aware midnight boundaries,
-- exactly like food_logs. logged_at is a verbatim display string, never parsed.
-- ============================================================================


-- ----------------------------------------------------------------------------
-- exercise_logs — confirmed workout records
-- ----------------------------------------------------------------------------
create table if not exists exercise_logs (
    id            uuid primary key default gen_random_uuid(),
    inbox_item_id uuid not null unique references inbox_items (id),
    owner_id      text not null default '<OWNER_USER_ID>',
    activity      text not null,
    duration_min  numeric,
    distance_km   numeric,
    sets          integer,
    reps          integer,
    intensity     text,
    calories      numeric,
    logged_at     text,
    notes         text,
    created_at    timestamptz not null default now()
);

comment on table exercise_logs is
    'Confirmed exercise/workout records. Exactly one row per source inbox_item (UNIQUE inbox_item_id). Written only by confirm_exercise_item() in the same transaction that confirms the inbox_item. Immutable in Phase 18 — no updated_at.';
comment on column exercise_logs.activity is
    'Activity description as extracted by the AI (e.g. "running", "gym - chest"). Required.';
comment on column exercise_logs.logged_at is
    'Free-text time/date as extracted by the AI (e.g. "this morning"). Stored as text — not parsed. NOT used for date filtering; filtering uses created_at.';

create index if not exists idx_exercise_logs_created_at on exercise_logs (created_at);


-- ----------------------------------------------------------------------------
-- RLS — deny direct anon/authenticated access (Phase 15a contract)
-- ----------------------------------------------------------------------------
alter table exercise_logs enable row level security;
alter table exercise_logs force row level security;
revoke all on table exercise_logs from anon, authenticated;


-- ----------------------------------------------------------------------------
-- confirm_exercise_item — atomic confirmation RPC
-- ----------------------------------------------------------------------------
-- Creates exactly one exercise_log for a pending exercise inbox_item, flips that
-- item to confirmed, and appends one memory_events row — all in one transaction.
-- Mirrors confirm_food_item (migration 0011/0012) exactly. owner_id is left to the
-- column default (single-owner); the inserts never set it.
-- ----------------------------------------------------------------------------
create or replace function confirm_exercise_item(
    p_inbox_id uuid,
    p_expected_updated_at timestamptz default null
)
returns jsonb
language plpgsql
as $$
declare
    v_item inbox_items%rowtype;
    v_log  exercise_logs%rowtype;
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
        select * into v_log from exercise_logs where inbox_item_id = p_inbox_id;
        if found then
            return jsonb_build_object(
                'inbox_item',   to_jsonb(v_item),
                'exercise_log', to_jsonb(v_log)
            );
        end if;
        raise exception 'confirmed_without_exercise_log: %', p_inbox_id
            using errcode = 'P0003';
    end if;

    -- 4. Must be pending to proceed.
    if v_item.review_status <> 'pending' then
        raise exception 'inbox_item_not_pending: % (%)', p_inbox_id, v_item.review_status
            using errcode = 'P0004';
    end if;

    -- 5. Must be an exercise item.
    if v_item.item_type <> 'exercise' then
        raise exception 'inbox_item_not_exercise: % (%)', p_inbox_id, v_item.item_type
            using errcode = 'P0005';
    end if;

    -- 6. Concurrency guard: reject a confirm built on a stale read.
    if p_expected_updated_at is not null and v_item.updated_at <> p_expected_updated_at then
        raise exception 'inbox_item_stale: %', p_inbox_id
            using errcode = 'P0006';
    end if;

    -- 7. Create exactly one exercise log. UNIQUE (inbox_item_id) backstops any race.
    insert into exercise_logs (
        inbox_item_id, activity, duration_min, distance_km, sets, reps,
        intensity, calories, logged_at, notes
    )
    values (
        v_item.id,
        v_item.structured_json->>'activity',
        (v_item.structured_json->>'duration_min')::numeric,
        (v_item.structured_json->>'distance_km')::numeric,
        (v_item.structured_json->>'sets')::integer,
        (v_item.structured_json->>'reps')::integer,
        nullif(v_item.structured_json->>'intensity', ''),
        (v_item.structured_json->>'calories')::numeric,
        nullif(v_item.structured_json->>'logged_at', ''),
        nullif(v_item.structured_json->>'notes', '')
    )
    returning * into v_log;

    -- 8. Confirm the inbox item using database UTC time.
    update inbox_items
       set review_status = 'confirmed',
           reviewed_at   = now()
     where id = p_inbox_id
    returning * into v_item;

    -- 9. Append exactly one memory event (Phase 15b contract).
    insert into memory_events (
        domain, event_type, payload_json, source_table, source_id, occurred_at
    )
    values (
        'exercise',
        'confirmed',
        jsonb_build_object(
            'activity',     v_log.activity,
            'duration_min', v_log.duration_min,
            'distance_km',  v_log.distance_km,
            'logged_at',    v_log.logged_at
        ),
        'exercise_logs',
        v_log.id,
        now()
    );

    return jsonb_build_object(
        'inbox_item',   to_jsonb(v_item),
        'exercise_log', to_jsonb(v_log)
    );
end;
$$;

-- RPC is backend/service-role only — never callable from the browser.
revoke all on function confirm_exercise_item(uuid, timestamptz) from public, anon, authenticated;
grant execute on function confirm_exercise_item(uuid, timestamptz) to service_role;
