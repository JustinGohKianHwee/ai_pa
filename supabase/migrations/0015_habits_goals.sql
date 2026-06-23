-- Replace <OWNER_USER_ID> with your Supabase owner UUID before running.
-- ============================================================================
-- Migration 0015 — Habits & Goals domain modules (Phase 20)
-- ============================================================================
-- Two definition-style domain tables following the tasks/food/exercise pattern and
-- the Phase 15b memory-event contract (one memory_events row per confirmation).
--
-- Pipeline reminder:
--     capture → classify/extract → pending inbox → review → atomic confirm + domain
--
-- Scope (locked):
--   * Habits are DEFINITION-ONLY — no check-ins, no streaks, no recurrence engine,
--     no mark-done. Immutable after confirm → no updated_at, no status.
--   * Goals carry a minimal status (active/achieved/abandoned), togglable post-confirm
--     (mirrors tasks.complete). Goal status changes do NOT write memory_events
--     (the 15b contract logs confirmations/snapshots only).
--
-- Invariants preserved (per existing modules):
--   * One inbox_item → at most one habit / one goal (UNIQUE inbox_item_id).
--   * Domain row + inbox confirmation + memory_event commit together or not at all.
--   * owner_id is default-filled single-owner (matches 0010/0011/0013).
--   * RLS deny-by-default; only the service-role backend reads/writes.
--
-- CRITICAL (Phase 18 lesson): the inbox_items.item_type CHECK constraint must be
-- widened to include 'habit' and 'goal', or confirming/classifying these items fails
-- with a postgrest APIError. (tests/test_item_type_constraint.py guards this.)
-- ============================================================================


-- ----------------------------------------------------------------------------
-- 0. Widen inbox_items.item_type to allow 'habit' and 'goal'
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
        'investment',
        'note',
        'journal',
        'unknown'
    ));


-- ----------------------------------------------------------------------------
-- 1. habits — confirmed habit definitions (immutable; definition-only)
-- ----------------------------------------------------------------------------
create table if not exists habits (
    id            uuid primary key default gen_random_uuid(),
    inbox_item_id uuid not null unique references inbox_items (id),
    owner_id      text not null default '<OWNER_USER_ID>',
    name          text not null,
    cadence       text,
    target        text,
    notes         text,
    created_at    timestamptz not null default now()
);

comment on table habits is
    'Confirmed habit definitions. One row per source inbox_item (UNIQUE inbox_item_id). Written only by confirm_habit_item() in the same transaction that confirms the inbox_item. Definition-only in Phase 20 — no check-ins/streaks, no updated_at.';
comment on column habits.cadence is
    'Free-text cadence as extracted by the AI (e.g. "daily", "3x a week"). NOT enum-constrained and NOT a scheduler — nothing acts on it in Phase 20.';

create index if not exists idx_habits_created_at on habits (created_at);

alter table habits enable row level security;
alter table habits force row level security;
revoke all on table habits from anon, authenticated;


-- ----------------------------------------------------------------------------
-- 2. goals — confirmed goals (status is mutable post-confirm)
-- ----------------------------------------------------------------------------
create table if not exists goals (
    id            uuid primary key default gen_random_uuid(),
    inbox_item_id uuid not null unique references inbox_items (id),
    owner_id      text not null default '<OWNER_USER_ID>',
    title         text not null,
    description   text,
    target        text,
    target_date   text,
    status        text not null default 'active'
        check (status in ('active', 'achieved', 'abandoned')),
    created_at    timestamptz not null default now(),
    updated_at    timestamptz not null default now()
);

comment on table goals is
    'Confirmed goals. One row per source inbox_item (UNIQUE inbox_item_id). Written only by confirm_goal_item(). status (active/achieved/abandoned) is the only field mutable after confirmation, via PATCH /goals/{id}/status (mirrors tasks.complete).';
comment on column goals.target_date is
    'Free-text target date exactly as extracted by the AI (e.g. "end 2027"). Stored as text — NOT parsed.';

create index if not exists idx_goals_status     on goals (status);
create index if not exists idx_goals_created_at  on goals (created_at);

-- Reuse the shared set_updated_at() trigger (created in migration 0001) for status changes.
drop trigger if exists trg_goals_set_updated_at on goals;
create trigger trg_goals_set_updated_at
    before update on goals
    for each row
    execute function set_updated_at();

alter table goals enable row level security;
alter table goals force row level security;
revoke all on table goals from anon, authenticated;


-- ----------------------------------------------------------------------------
-- 3. confirm_habit_item — atomic confirmation RPC
-- ----------------------------------------------------------------------------
create or replace function confirm_habit_item(
    p_inbox_id uuid,
    p_expected_updated_at timestamptz default null
)
returns jsonb
language plpgsql
as $$
declare
    v_item  inbox_items%rowtype;
    v_habit habits%rowtype;
begin
    select * into v_item from inbox_items where id = p_inbox_id for update;

    if not found then
        raise exception 'inbox_item_not_found: %', p_inbox_id using errcode = 'P0002';
    end if;

    if v_item.review_status = 'confirmed' then
        select * into v_habit from habits where inbox_item_id = p_inbox_id;
        if found then
            return jsonb_build_object('inbox_item', to_jsonb(v_item), 'habit', to_jsonb(v_habit));
        end if;
        raise exception 'confirmed_without_habit: %', p_inbox_id using errcode = 'P0003';
    end if;

    if v_item.review_status <> 'pending' then
        raise exception 'inbox_item_not_pending: % (%)', p_inbox_id, v_item.review_status
            using errcode = 'P0004';
    end if;

    if v_item.item_type <> 'habit' then
        raise exception 'inbox_item_not_habit: % (%)', p_inbox_id, v_item.item_type
            using errcode = 'P0005';
    end if;

    if p_expected_updated_at is not null and v_item.updated_at <> p_expected_updated_at then
        raise exception 'inbox_item_stale: %', p_inbox_id using errcode = 'P0006';
    end if;

    insert into habits (inbox_item_id, name, cadence, target, notes)
    values (
        v_item.id,
        v_item.structured_json->>'name',
        nullif(v_item.structured_json->>'cadence', ''),
        nullif(v_item.structured_json->>'target', ''),
        nullif(v_item.structured_json->>'notes', '')
    )
    returning * into v_habit;

    update inbox_items
       set review_status = 'confirmed',
           reviewed_at   = now()
     where id = p_inbox_id
    returning * into v_item;

    insert into memory_events (
        domain, event_type, payload_json, source_table, source_id, occurred_at
    )
    values (
        'habit',
        'confirmed',
        jsonb_build_object(
            'name',    v_habit.name,
            'cadence', v_habit.cadence,
            'target',  v_habit.target
        ),
        'habits',
        v_habit.id,
        now()
    );

    return jsonb_build_object('inbox_item', to_jsonb(v_item), 'habit', to_jsonb(v_habit));
end;
$$;


-- ----------------------------------------------------------------------------
-- 4. confirm_goal_item — atomic confirmation RPC
-- ----------------------------------------------------------------------------
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

    -- status defaults to 'active' (column default); not classified or set here.
    insert into goals (inbox_item_id, title, description, target, target_date)
    values (
        v_item.id,
        v_item.structured_json->>'title',
        nullif(v_item.structured_json->>'description', ''),
        nullif(v_item.structured_json->>'target', ''),
        nullif(v_item.structured_json->>'target_date', '')
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
            'title',       v_goal.title,
            'target',      v_goal.target,
            'target_date', v_goal.target_date,
            'status',      v_goal.status
        ),
        'goals',
        v_goal.id,
        now()
    );

    return jsonb_build_object('inbox_item', to_jsonb(v_item), 'goal', to_jsonb(v_goal));
end;
$$;


-- ----------------------------------------------------------------------------
-- 5. Grants — RPCs are backend/service-role only
-- ----------------------------------------------------------------------------
revoke all on function confirm_habit_item(uuid, timestamptz) from public, anon, authenticated;
grant execute on function confirm_habit_item(uuid, timestamptz) to service_role;

revoke all on function confirm_goal_item(uuid, timestamptz) from public, anon, authenticated;
grant execute on function confirm_goal_item(uuid, timestamptz) to service_role;
