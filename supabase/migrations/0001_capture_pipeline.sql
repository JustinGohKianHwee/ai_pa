-- ============================================================================
-- Migration 0001 — Capture pipeline core schema
-- ============================================================================
-- Creates the three core tables that power the review-first capture pipeline:
--
--     capture → classify/extract → pending inbox → review → confirm → domain
--
--   1. capture_events — raw input history (written BEFORE any AI work)
--   2. inbox_items    — classified items awaiting / recording user review
--   3. agent_runs     — append-only audit of every AI model call
--
-- Invariants this schema preserves:
--   * Raw captures are stored before AI runs, so a capture is never lost.
--   * AI output lands in inbox_items first. No domain record is created here;
--     domain tables arrive per-module in later phases and are only written
--     after explicit user confirmation.
--   * Classification failure is a processing_status on capture_events, never an
--     item_type. A failed capture still produces a reviewable inbox_item with
--     item_type = 'unknown' and review_status = 'needs_manual_classification'.
--
-- NOT in this migration (deferred by design):
--   * Domain tables (tasks, money_events, food_logs, ...) — per-module, later.
--   * Row Level Security / auth — Phase 15.
--   * pgvector / memory_chunks — Phase 15.
--
-- gen_random_uuid() is available natively in Supabase Postgres (pgcrypto).
-- ============================================================================


-- ----------------------------------------------------------------------------
-- capture_events — durable raw input history
-- ----------------------------------------------------------------------------
-- One row per inbound capture (Telegram text/voice, web form, etc.). Raw source
-- fields are immutable ground truth. Processing fields such as transcript,
-- processing_status, and safe metadata may be updated by later pipeline phases.
create table if not exists capture_events (
    id                uuid primary key default gen_random_uuid(),
    source            text not null,
    source_message_id text,
    raw_text          text,
    transcript        text,
    audio_file_id     text,
    processing_status text not null default 'received'
        check (processing_status in (
            'received',
            'classified',
            'classification_failed',
            'invalid_ai_output'
        )),
    metadata          jsonb not null default '{}'::jsonb,
    created_at        timestamptz not null default now()
);

comment on table  capture_events is
    'Durable raw input history written before AI work. Raw source fields are immutable; processing fields may advance.';
comment on column capture_events.source is
    'Origin of the capture, e.g. telegram_text, telegram_voice, web_form.';
comment on column capture_events.source_message_id is
    'External id from the source system (e.g. Telegram message id) for dedupe/trace.';
comment on column capture_events.raw_text is
    'Original text exactly as received (null for voice until transcribed).';
comment on column capture_events.transcript is
    'Speech-to-text transcript for voice captures (Phase 10+).';
comment on column capture_events.audio_file_id is
    'Reference to the stored original audio file (voice only).';
comment on column capture_events.processing_status is
    'Where this capture is in the AI pipeline. classification_failed / invalid_ai_output mark failures; the capture itself is still preserved.';
comment on column capture_events.metadata is
    'Free-form JSON for source-specific context and safe error metadata.';


-- ----------------------------------------------------------------------------
-- inbox_items — the review gate
-- ----------------------------------------------------------------------------
-- One row per processed capture awaiting or recording user review. Nothing
-- becomes a domain record until a user explicitly confirms a valid pending row.
create table if not exists inbox_items (
    id              uuid primary key default gen_random_uuid(),
    capture_event_id uuid not null references capture_events (id),
    item_type       text not null
        check (item_type in (
            'task',
            'finance',
            'calendar',
            'food',
            'investment',
            'note',
            'journal',
            'unknown'
        )),
    review_status   text not null default 'pending'
        check (review_status in (
            'pending',
            'needs_manual_classification',
            'confirmed',
            'rejected'
        )),
    title           text,
    body            text,
    structured_json jsonb not null default '{}'::jsonb,
    confidence      numeric
        check (confidence is null or (confidence >= 0 and confidence <= 1)),
    reviewed_at     timestamptz,
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now(),
    check (
        (review_status in ('pending', 'needs_manual_classification') and reviewed_at is null)
        or
        (review_status in ('confirmed', 'rejected') and reviewed_at is not null)
    ),
    check (review_status <> 'needs_manual_classification' or item_type = 'unknown')
);

comment on table  inbox_items is
    'Review gate. Classified items await user review here; domain records are only created after explicit confirmation.';
comment on column inbox_items.capture_event_id is
    'The raw capture this item was derived from.';
comment on column inbox_items.item_type is
    'AI-assigned type. classification_failed is NOT a value here — failures use item_type = unknown.';
comment on column inbox_items.review_status is
    'User review state. needs_manual_classification = AI failed/invalid; must be edited to a valid type before it can be confirmed.';
comment on column inbox_items.title is
    'Short human-readable summary of the item.';
comment on column inbox_items.body is
    'Longer free-text detail for the item.';
comment on column inbox_items.structured_json is
    'Structured fields extracted for this item_type (shape varies by type).';
comment on column inbox_items.confidence is
    'AI confidence in the classification, 0–1 (null if not classified).';
comment on column inbox_items.reviewed_at is
    'When the user confirmed or rejected this item (null until reviewed).';


-- ----------------------------------------------------------------------------
-- agent_runs — append-only AI call audit
-- ----------------------------------------------------------------------------
-- One row per AI model call (classification, transcription, extraction). Used
-- for transparency and debugging misclassifications or failed processing.
create table if not exists agent_runs (
    id              uuid primary key default gen_random_uuid(),
    capture_event_id uuid references capture_events (id),
    inbox_item_id   uuid references inbox_items (id),
    agent_name      text not null,
    model           text,
    input_json      jsonb not null default '{}'::jsonb,
    output_json     jsonb not null default '{}'::jsonb,
    error_json      jsonb,
    created_at      timestamptz not null default now()
);

comment on table  agent_runs is
    'Append-only audit of every AI model call (classify / transcribe / extract).';
comment on column agent_runs.capture_event_id is
    'The capture this call was about (null if not tied to a specific capture).';
comment on column agent_runs.inbox_item_id is
    'The inbox item this call produced/updated (null if not applicable).';
comment on column agent_runs.agent_name is
    'Logical name of the agent/step, e.g. classifier, transcriber.';
comment on column agent_runs.model is
    'Model identifier used, e.g. claude-sonnet-4-6, whisper-1.';
comment on column agent_runs.input_json is
    'Safe summary of the call input (not necessarily the full prompt).';
comment on column agent_runs.output_json is
    'Safe summary of the call output.';
comment on column agent_runs.error_json is
    'Error detail when the call failed (null on success).';


-- ----------------------------------------------------------------------------
-- updated_at maintenance for inbox_items
-- ----------------------------------------------------------------------------
-- inbox_items is the only mutable core table (status moves pending -> confirmed
-- /rejected, fields get edited during review). Keep updated_at current via a
-- trigger so application code does not have to remember to set it.
create or replace function set_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists trg_inbox_items_set_updated_at on inbox_items;
create trigger trg_inbox_items_set_updated_at
    before update on inbox_items
    for each row
    execute function set_updated_at();


-- ----------------------------------------------------------------------------
-- Indexes
-- ----------------------------------------------------------------------------
-- The dashboard inbox filters by review_status (pending + needs_manual_
-- classification) and item_type, and orders by created_at. The append-only
-- tables are queried chronologically.
create index if not exists idx_inbox_items_review_status on inbox_items (review_status);
create index if not exists idx_inbox_items_item_type     on inbox_items (item_type);
create index if not exists idx_inbox_items_created_at     on inbox_items (created_at);
create index if not exists idx_capture_events_created_at  on capture_events (created_at);
create index if not exists idx_agent_runs_created_at      on agent_runs (created_at);
