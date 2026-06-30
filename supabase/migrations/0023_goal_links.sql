-- Replace <OWNER_USER_ID> with your Supabase owner UUID before running.
-- ============================================================================
-- Migration 0023 — Goal → activity attribution (Phase 25)
-- ============================================================================
-- Explicit, user-created metadata links between a goal and confirmed domain records.
-- Goal links are not domain records, do not enter the capture→confirm pipeline, and
-- do not write memory_events. They are reversible annotations, like goal status changes.
-- ============================================================================

create table if not exists goal_links (
    id           uuid primary key default gen_random_uuid(),
    owner_id     text not null default '<OWNER_USER_ID>',
    goal_id      uuid not null references goals (id),
    source_table text not null
        check (source_table in (
            'tasks',
            'money_events',
            'food_logs',
            'calendar_intents',
            'exercise_logs',
            'habits',
            'decisions',
            'notes',
            'journal_entries',
            'lifestyle_checkins',
            'manual_financial_snapshots'
        )),
    source_id    uuid not null,
    note         text,
    created_at   timestamptz not null default now(),
    unique (goal_id, source_table, source_id)
);

comment on table goal_links is
    'Explicit user-created links between a goal and a confirmed domain record (attribution). Metadata only — not a domain record, not in the capture→confirm pipeline, no memory_events.';

create index if not exists idx_goal_links_goal on goal_links (owner_id, goal_id);

alter table goal_links enable row level security;
alter table goal_links force row level security;
revoke all on table goal_links from anon, authenticated;
