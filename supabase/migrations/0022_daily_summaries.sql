-- Replace <OWNER_USER_ID> with your Supabase owner UUID before running.
-- ============================================================================
-- Migration 0022 — Daily summaries + memory_events.importance (Phase 24)
-- ============================================================================
-- Phase 24 is the first SYNTHESIS layer: a forward-looking daily briefing and a
-- weekly reflection, both DETERMINISTIC (computed from structured records, never
-- LLM — egress is gated at Phase 27). The generated summaries are persisted into
-- daily_summaries as the artifact the future memory pipeline (Phase 26/28) will
-- distill/embed.
--
-- Also adds a nullable importance to memory_events as retrieval-ranking prep for
-- Phase 28 (Generative-Agents recency × importance × relevance). Column only — no
-- backfill, no confirm-RPC changes; population is deferred to Phase 26/28.
-- ============================================================================


-- ----------------------------------------------------------------------------
-- 0. memory_events.importance — nullable retrieval-ranking signal (prep only)
-- ----------------------------------------------------------------------------
alter table memory_events
    add column if not exists importance smallint
        check (importance is null or (importance >= 1 and importance <= 10));

comment on column memory_events.importance is
    'Optional 1-10 retrieval-ranking signal (Phase 24 prep; populated in Phase 26/28). Nullable.';


-- ----------------------------------------------------------------------------
-- 1. daily_summaries — persisted deterministic briefing/reflection artifacts
-- ----------------------------------------------------------------------------
create table if not exists daily_summaries (
    id           uuid primary key default gen_random_uuid(),
    owner_id     text not null default '<OWNER_USER_ID>',
    summary_date date not null,
    kind         text not null
        check (kind in ('daily', 'weekly')),
    payload_json jsonb not null default '{}'::jsonb,
    generated_at timestamptz not null default now(),
    unique (owner_id, summary_date, kind)
);

comment on table daily_summaries is
    'Persisted deterministic synthesis artifacts (Phase 24). One row per (owner_id, summary_date, kind=daily|weekly); regenerated idempotently. Derived from confirmed records + snapshots + memory_events — NOT a domain record and not part of the capture→confirm pipeline.';

create index if not exists idx_daily_summaries_owner_date
    on daily_summaries (owner_id, summary_date desc);

alter table daily_summaries enable row level security;
alter table daily_summaries force row level security;
revoke all on table daily_summaries from anon, authenticated;
