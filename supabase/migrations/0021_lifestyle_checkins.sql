-- Replace <OWNER_USER_ID> with your Supabase owner UUID before running.
-- ============================================================================
-- Migration 0021 — Lifestyle check-ins domain module (Phase 23b)
-- ============================================================================
-- A review-first reflective daily check-in, following the decisions/notes pattern
-- and the Phase 15b memory-event contract.
--
-- Pipeline reminder:
--     capture → classify/extract → pending inbox → review → atomic confirm + domain
--
-- Scope (locked):
--   * A lightweight self-report: energy (1-5), mood (free text), sleep_hours,
--     stress (1-5), activity (free text), optional notes, and a verbatim `as_of` day.
--   * Immutable after confirmation (no status, no updated_at): edited in the inbox
--     BEFORE confirmation, not here.
--   * Each confirm writes exactly one memory_events row (15b contract).
--   * EXPLICITLY NOT a medical/diagnostic tool — structured rows for later personal
--     correlation only. No diagnosis, no scoring, no auto-advice.
--
-- CRITICAL (Phase 18/20 lesson): widen inbox_items.item_type CHECK to include
-- 'checkin', or confirming/classifying these items fails with a postgrest APIError.
-- (tests/test_item_type_constraint.py guards this.)
-- ============================================================================


-- ----------------------------------------------------------------------------
-- 0. Widen inbox_items.item_type to allow 'checkin'
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
        'checkin',
        'unknown'
    ));


-- ----------------------------------------------------------------------------
-- 1. lifestyle_checkins — confirmed daily self-report entries
-- ----------------------------------------------------------------------------
create table if not exists lifestyle_checkins (
    id            uuid primary key default gen_random_uuid(),
    inbox_item_id uuid not null unique references inbox_items (id),
    owner_id      text not null default '<OWNER_USER_ID>',
    as_of         text,
    energy        smallint check (energy is null or (energy >= 1 and energy <= 5)),
    mood          text,
    sleep_hours   numeric check (sleep_hours is null or (sleep_hours >= 0 and sleep_hours <= 24)),
    stress        smallint check (stress is null or (stress >= 1 and stress <= 5)),
    activity      text,
    notes         text,
    created_at    timestamptz not null default now()
);

comment on table lifestyle_checkins is
    'Confirmed lifestyle check-ins (self-report). One row per source inbox_item (UNIQUE inbox_item_id). Written only by confirm_checkin_item(). Immutable after confirmation. NOT a medical/diagnostic tool — structured personal log only.';
comment on column lifestyle_checkins.as_of is
    'Free-text day the check-in refers to, verbatim from the AI (e.g. "today"). Stored as text — NOT parsed.';
comment on column lifestyle_checkins.energy is '1-5 self-rated energy (nullable).';
comment on column lifestyle_checkins.stress is '1-5 self-rated stress (nullable).';

create index if not exists idx_lifestyle_checkins_created_at on lifestyle_checkins (created_at);

alter table lifestyle_checkins enable row level security;
alter table lifestyle_checkins force row level security;
revoke all on table lifestyle_checkins from anon, authenticated;


-- ----------------------------------------------------------------------------
-- 2. confirm_checkin_item — atomic confirmation RPC
-- ----------------------------------------------------------------------------
create or replace function confirm_checkin_item(
    p_inbox_id uuid,
    p_expected_updated_at timestamptz default null
)
returns jsonb
language plpgsql
as $$
declare
    v_item    inbox_items%rowtype;
    v_checkin lifestyle_checkins%rowtype;
begin
    select * into v_item from inbox_items where id = p_inbox_id for update;

    if not found then
        raise exception 'inbox_item_not_found: %', p_inbox_id using errcode = 'P0002';
    end if;

    if v_item.review_status = 'confirmed' then
        select * into v_checkin from lifestyle_checkins where inbox_item_id = p_inbox_id;
        if found then
            return jsonb_build_object(
                'inbox_item', to_jsonb(v_item),
                'checkin',    to_jsonb(v_checkin)
            );
        end if;
        raise exception 'confirmed_without_checkin: %', p_inbox_id using errcode = 'P0003';
    end if;

    if v_item.review_status <> 'pending' then
        raise exception 'inbox_item_not_pending: % (%)', p_inbox_id, v_item.review_status
            using errcode = 'P0004';
    end if;

    if v_item.item_type <> 'checkin' then
        raise exception 'inbox_item_not_checkin: % (%)', p_inbox_id, v_item.item_type
            using errcode = 'P0005';
    end if;

    if p_expected_updated_at is not null and v_item.updated_at <> p_expected_updated_at then
        raise exception 'inbox_item_stale: %', p_inbox_id using errcode = 'P0006';
    end if;

    insert into lifestyle_checkins (
        inbox_item_id, as_of, energy, mood, sleep_hours, stress, activity, notes
    )
    values (
        v_item.id,
        nullif(v_item.structured_json->>'as_of', ''),
        (v_item.structured_json->>'energy')::smallint,
        nullif(v_item.structured_json->>'mood', ''),
        (v_item.structured_json->>'sleep_hours')::numeric,
        (v_item.structured_json->>'stress')::smallint,
        nullif(v_item.structured_json->>'activity', ''),
        nullif(v_item.structured_json->>'notes', '')
    )
    returning * into v_checkin;

    update inbox_items
       set review_status = 'confirmed',
           reviewed_at   = now()
     where id = p_inbox_id
    returning * into v_item;

    insert into memory_events (
        domain, event_type, payload_json, source_table, source_id, occurred_at
    )
    values (
        'checkin',
        'confirmed',
        jsonb_build_object(
            'as_of',       v_checkin.as_of,
            'energy',      v_checkin.energy,
            'mood',        v_checkin.mood,
            'sleep_hours', v_checkin.sleep_hours,
            'stress',      v_checkin.stress,
            'activity',    v_checkin.activity
        ),
        'lifestyle_checkins',
        v_checkin.id,
        now()
    );

    return jsonb_build_object(
        'inbox_item', to_jsonb(v_item),
        'checkin',    to_jsonb(v_checkin)
    );
end;
$$;


-- ----------------------------------------------------------------------------
-- 3. Grants — RPC is backend/service-role only
-- ----------------------------------------------------------------------------
revoke all on function confirm_checkin_item(uuid, timestamptz) from public, anon, authenticated;
grant execute on function confirm_checkin_item(uuid, timestamptz) to service_role;
