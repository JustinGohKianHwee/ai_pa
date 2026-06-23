-- Replace <OWNER_USER_ID> with your Supabase owner UUID before running.
-- ============================================================================
-- Migration 0016 — Decision Journal domain module (Phase 21)
-- ============================================================================
-- A review-first domain module following the goals pattern (status mutable
-- post-confirm) and the Phase 15b memory-event contract.
--
-- Pipeline reminder:
--     capture → classify/extract → pending inbox → review → atomic confirm + domain
--
-- Scope (locked):
--   * Records a decision made: the choice + reason + options + expected outcome +
--     the user's confidence. Only `decision` is required; everything else optional.
--   * status (active/reversed/archived) is the only field mutable after confirmation,
--     via PATCH /decisions/{id}/status (mirrors goals). Status changes do NOT write
--     memory_events (15b contract logs confirmations/snapshots only).
--   * NO outcome-review, quality scoring, prediction, attribution, or related_goal_id.
--
-- CRITICAL (Phase 18/20 lesson): widen inbox_items.item_type CHECK to include
-- 'decision', or confirming/classifying these items fails with a postgrest APIError.
-- (tests/test_item_type_constraint.py guards this.)
-- ============================================================================


-- ----------------------------------------------------------------------------
-- 0. Widen inbox_items.item_type to allow 'decision'
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
        'investment',
        'note',
        'journal',
        'unknown'
    ));


-- ----------------------------------------------------------------------------
-- 1. decisions — confirmed decision records (status mutable post-confirm)
-- ----------------------------------------------------------------------------
create table if not exists decisions (
    id                 uuid primary key default gen_random_uuid(),
    inbox_item_id      uuid not null unique references inbox_items (id),
    owner_id           text not null default 'd64140ca-fad6-4444-84f6-96b976d5f784',
    decision           text not null,
    reason             text,
    options_considered text,
    expected_outcome   text,
    confidence         numeric
        check (confidence is null or (confidence >= 0 and confidence <= 1)),
    category           text,
    decided_at         text,
    status             text not null default 'active'
        check (status in ('active', 'reversed', 'archived')),
    notes              text,
    created_at         timestamptz not null default now(),
    updated_at         timestamptz not null default now()
);

comment on table decisions is
    'Confirmed decision-journal entries. One row per source inbox_item (UNIQUE inbox_item_id). Written only by confirm_decision_item(). status (active/reversed/archived) is the only field mutable after confirmation, via PATCH /decisions/{id}/status.';
comment on column decisions.decision is
    'The decision/choice made. Required — sourced from DecisionStructuredJson.decision.';
comment on column decisions.confidence is
    'The user''s confidence in the decision, 0..1 (distinct from the classifier confidence). Nullable.';
comment on column decisions.decided_at is
    'Free-text date the decision was made, verbatim from the AI (e.g. "today"). Stored as text — NOT parsed.';

create index if not exists idx_decisions_status     on decisions (status);
create index if not exists idx_decisions_created_at on decisions (created_at);

-- Reuse the shared set_updated_at() trigger (migration 0001) for status changes.
drop trigger if exists trg_decisions_set_updated_at on decisions;
create trigger trg_decisions_set_updated_at
    before update on decisions
    for each row
    execute function set_updated_at();

alter table decisions enable row level security;
alter table decisions force row level security;
revoke all on table decisions from anon, authenticated;


-- ----------------------------------------------------------------------------
-- 2. confirm_decision_item — atomic confirmation RPC
-- ----------------------------------------------------------------------------
create or replace function confirm_decision_item(
    p_inbox_id uuid,
    p_expected_updated_at timestamptz default null
)
returns jsonb
language plpgsql
as $$
declare
    v_item     inbox_items%rowtype;
    v_decision decisions%rowtype;
begin
    select * into v_item from inbox_items where id = p_inbox_id for update;

    if not found then
        raise exception 'inbox_item_not_found: %', p_inbox_id using errcode = 'P0002';
    end if;

    if v_item.review_status = 'confirmed' then
        select * into v_decision from decisions where inbox_item_id = p_inbox_id;
        if found then
            return jsonb_build_object(
                'inbox_item', to_jsonb(v_item),
                'decision',   to_jsonb(v_decision)
            );
        end if;
        raise exception 'confirmed_without_decision: %', p_inbox_id using errcode = 'P0003';
    end if;

    if v_item.review_status <> 'pending' then
        raise exception 'inbox_item_not_pending: % (%)', p_inbox_id, v_item.review_status
            using errcode = 'P0004';
    end if;

    if v_item.item_type <> 'decision' then
        raise exception 'inbox_item_not_decision: % (%)', p_inbox_id, v_item.item_type
            using errcode = 'P0005';
    end if;

    if p_expected_updated_at is not null and v_item.updated_at <> p_expected_updated_at then
        raise exception 'inbox_item_stale: %', p_inbox_id using errcode = 'P0006';
    end if;

    insert into decisions (
        inbox_item_id, decision, reason, options_considered, expected_outcome,
        confidence, category, decided_at, notes
    )
    values (
        v_item.id,
        v_item.structured_json->>'decision',
        nullif(v_item.structured_json->>'reason', ''),
        nullif(v_item.structured_json->>'options_considered', ''),
        nullif(v_item.structured_json->>'expected_outcome', ''),
        (v_item.structured_json->>'confidence')::numeric,
        nullif(v_item.structured_json->>'category', ''),
        nullif(v_item.structured_json->>'decided_at', ''),
        nullif(v_item.structured_json->>'notes', '')
    )
    returning * into v_decision;

    update inbox_items
       set review_status = 'confirmed',
           reviewed_at   = now()
     where id = p_inbox_id
    returning * into v_item;

    insert into memory_events (
        domain, event_type, payload_json, source_table, source_id, occurred_at
    )
    values (
        'decision',
        'confirmed',
        jsonb_build_object(
            'decision',   v_decision.decision,
            'category',   v_decision.category,
            'confidence', v_decision.confidence,
            'decided_at', v_decision.decided_at
        ),
        'decisions',
        v_decision.id,
        now()
    );

    return jsonb_build_object(
        'inbox_item', to_jsonb(v_item),
        'decision',   to_jsonb(v_decision)
    );
end;
$$;


-- ----------------------------------------------------------------------------
-- 3. Grants — RPC is backend/service-role only
-- ----------------------------------------------------------------------------
revoke all on function confirm_decision_item(uuid, timestamptz) from public, anon, authenticated;
grant execute on function confirm_decision_item(uuid, timestamptz) to service_role;
