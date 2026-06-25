-- Replace <OWNER_USER_ID> with your Supabase owner UUID before running.
-- ============================================================================
-- Migration 0019 — Statement import staging (Phase 22d)
-- ============================================================================
-- Review-first bank/card statement import. A statement is parsed into immutable
-- staged rows. Each row is either:
--   * MATCHED to an existing confirmed money_event (currency + amount) → no action,
--     just recorded as verified; OR
--   * IMPORTED → a capture_event (source='statement_import') + a pending finance
--     inbox_item is created so the row flows through the SAME review → confirm pipeline
--     (confirm_finance_item) as any other capture. Nothing becomes a money_event without
--     explicit user confirmation in the inbox.
--
-- No money_events schema change and no auto-confirm: statement import is just a new
-- capture surface + a dedup/match layer. money_events still require a confirmed inbox_item
-- (UNIQUE inbox_item_id), so imported rows are reviewed individually.
--
-- v1 matching is deterministic on (currency, amount) — money_events.occurred_at is free
-- text and created_at is log time, so date proximity is unreliable; documented limitation.
-- ============================================================================


-- ----------------------------------------------------------------------------
-- statement_imports — one row per uploaded statement
-- ----------------------------------------------------------------------------
create table if not exists statement_imports (
    id           uuid primary key default gen_random_uuid(),
    owner_id     text not null default '<OWNER_USER_ID>',
    source_label text,
    row_count    integer not null default 0,
    matched_count integer not null default 0,
    imported_count integer not null default 0,
    created_at   timestamptz not null default now()
);

alter table statement_imports enable row level security;
alter table statement_imports force row level security;
revoke all on table statement_imports from anon, authenticated;

create index if not exists idx_statement_imports_created_at on statement_imports (created_at);


-- ----------------------------------------------------------------------------
-- statement_rows — immutable parsed rows; status records match/import outcome
-- ----------------------------------------------------------------------------
create table if not exists statement_rows (
    id                    uuid primary key default gen_random_uuid(),
    import_id             uuid not null references statement_imports (id),
    owner_id              text not null default '<OWNER_USER_ID>',
    occurred_on           text,
    description           text,
    amount                numeric not null,
    currency              text not null,
    status                text not null
        check (status in ('matched', 'imported')),
    matched_money_event_id uuid references money_events (id),
    inbox_item_id         uuid references inbox_items (id),
    created_at            timestamptz not null default now()
);

alter table statement_rows enable row level security;
alter table statement_rows force row level security;
revoke all on table statement_rows from anon, authenticated;

create index if not exists idx_statement_rows_import on statement_rows (import_id);

comment on table statement_rows is
    'Immutable parsed statement rows. status=matched → an existing money_event matched (currency+amount); status=imported → a capture_event + pending finance inbox_item was created for review. Never creates a money_event directly.';
