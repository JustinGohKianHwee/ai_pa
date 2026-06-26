-- Replace <OWNER_USER_ID> with your Supabase owner UUID before running.
-- ============================================================================
-- Migration 0020 — Notes & Journal domain module (Phase 23a)
-- ============================================================================
-- Two review-first free-form text domains, following the decisions pattern
-- (migration 0016) and the Phase 15b memory-event contract.
--
-- Pipeline reminder:
--     capture → classify/extract → pending inbox → review → atomic confirm + domain
--
-- Scope (locked):
--   * notes          — a quick free-form note: content + optional tags.
--   * journal_entries — a reflective journal entry: content + optional mood.
--   * Both are immutable after confirmation (no status, no updated_at): content is
--     edited in the inbox BEFORE confirmation, not here.
--   * Each confirm writes exactly one memory_events row (15b contract).
--
-- NOTE: inbox_items.item_type already allows 'note' and 'journal' (migration 0016),
-- so NO CHECK widening is needed here.
-- ============================================================================


-- ----------------------------------------------------------------------------
-- 1. notes — confirmed quick notes (content + tags)
-- ----------------------------------------------------------------------------
create table if not exists notes (
    id            uuid primary key default gen_random_uuid(),
    inbox_item_id uuid not null unique references inbox_items (id),
    owner_id      text not null default '<OWNER_USER_ID>',
    content       text not null,
    tags          text[] not null default '{}',
    created_at    timestamptz not null default now()
);

comment on table notes is
    'Confirmed free-form notes. One row per source inbox_item (UNIQUE inbox_item_id). Written only by confirm_note_item(). Immutable after confirmation.';

create index if not exists idx_notes_created_at on notes (created_at);

alter table notes enable row level security;
alter table notes force row level security;
revoke all on table notes from anon, authenticated;


-- ----------------------------------------------------------------------------
-- 2. journal_entries — confirmed reflective entries (content + mood)
-- ----------------------------------------------------------------------------
create table if not exists journal_entries (
    id            uuid primary key default gen_random_uuid(),
    inbox_item_id uuid not null unique references inbox_items (id),
    owner_id      text not null default '<OWNER_USER_ID>',
    content       text not null,
    mood          text,
    created_at    timestamptz not null default now()
);

comment on table journal_entries is
    'Confirmed journal entries. One row per source inbox_item (UNIQUE inbox_item_id). Written only by confirm_journal_item(). Immutable after confirmation.';

create index if not exists idx_journal_entries_created_at on journal_entries (created_at);

alter table journal_entries enable row level security;
alter table journal_entries force row level security;
revoke all on table journal_entries from anon, authenticated;


-- ----------------------------------------------------------------------------
-- 3. confirm_note_item — atomic confirmation RPC
-- ----------------------------------------------------------------------------
create or replace function confirm_note_item(
    p_inbox_id uuid,
    p_expected_updated_at timestamptz default null
)
returns jsonb
language plpgsql
as $$
declare
    v_item inbox_items%rowtype;
    v_note notes%rowtype;
begin
    select * into v_item from inbox_items where id = p_inbox_id for update;

    if not found then
        raise exception 'inbox_item_not_found: %', p_inbox_id using errcode = 'P0002';
    end if;

    if v_item.review_status = 'confirmed' then
        select * into v_note from notes where inbox_item_id = p_inbox_id;
        if found then
            return jsonb_build_object(
                'inbox_item', to_jsonb(v_item),
                'note',       to_jsonb(v_note)
            );
        end if;
        raise exception 'confirmed_without_note: %', p_inbox_id using errcode = 'P0003';
    end if;

    if v_item.review_status <> 'pending' then
        raise exception 'inbox_item_not_pending: % (%)', p_inbox_id, v_item.review_status
            using errcode = 'P0004';
    end if;

    if v_item.item_type <> 'note' then
        raise exception 'inbox_item_not_note: % (%)', p_inbox_id, v_item.item_type
            using errcode = 'P0005';
    end if;

    if p_expected_updated_at is not null and v_item.updated_at <> p_expected_updated_at then
        raise exception 'inbox_item_stale: %', p_inbox_id using errcode = 'P0006';
    end if;

    insert into notes (inbox_item_id, content, tags)
    values (
        v_item.id,
        v_item.structured_json->>'content',
        coalesce(array(select jsonb_array_elements_text(v_item.structured_json->'tags')), '{}')
    )
    returning * into v_note;

    update inbox_items
       set review_status = 'confirmed',
           reviewed_at   = now()
     where id = p_inbox_id
    returning * into v_item;

    insert into memory_events (
        domain, event_type, payload_json, source_table, source_id, occurred_at
    )
    values (
        'note',
        'confirmed',
        jsonb_build_object(
            'content', v_note.content,
            'tags',    to_jsonb(v_note.tags)
        ),
        'notes',
        v_note.id,
        now()
    );

    return jsonb_build_object(
        'inbox_item', to_jsonb(v_item),
        'note',       to_jsonb(v_note)
    );
end;
$$;


-- ----------------------------------------------------------------------------
-- 4. confirm_journal_item — atomic confirmation RPC
-- ----------------------------------------------------------------------------
create or replace function confirm_journal_item(
    p_inbox_id uuid,
    p_expected_updated_at timestamptz default null
)
returns jsonb
language plpgsql
as $$
declare
    v_item  inbox_items%rowtype;
    v_entry journal_entries%rowtype;
begin
    select * into v_item from inbox_items where id = p_inbox_id for update;

    if not found then
        raise exception 'inbox_item_not_found: %', p_inbox_id using errcode = 'P0002';
    end if;

    if v_item.review_status = 'confirmed' then
        select * into v_entry from journal_entries where inbox_item_id = p_inbox_id;
        if found then
            return jsonb_build_object(
                'inbox_item',    to_jsonb(v_item),
                'journal_entry', to_jsonb(v_entry)
            );
        end if;
        raise exception 'confirmed_without_journal: %', p_inbox_id using errcode = 'P0003';
    end if;

    if v_item.review_status <> 'pending' then
        raise exception 'inbox_item_not_pending: % (%)', p_inbox_id, v_item.review_status
            using errcode = 'P0004';
    end if;

    if v_item.item_type <> 'journal' then
        raise exception 'inbox_item_not_journal: % (%)', p_inbox_id, v_item.item_type
            using errcode = 'P0005';
    end if;

    if p_expected_updated_at is not null and v_item.updated_at <> p_expected_updated_at then
        raise exception 'inbox_item_stale: %', p_inbox_id using errcode = 'P0006';
    end if;

    insert into journal_entries (inbox_item_id, content, mood)
    values (
        v_item.id,
        v_item.structured_json->>'content',
        nullif(v_item.structured_json->>'mood', '')
    )
    returning * into v_entry;

    update inbox_items
       set review_status = 'confirmed',
           reviewed_at   = now()
     where id = p_inbox_id
    returning * into v_item;

    insert into memory_events (
        domain, event_type, payload_json, source_table, source_id, occurred_at
    )
    values (
        'journal',
        'confirmed',
        jsonb_build_object(
            'content', v_entry.content,
            'mood',    v_entry.mood
        ),
        'journal_entries',
        v_entry.id,
        now()
    );

    return jsonb_build_object(
        'inbox_item',    to_jsonb(v_item),
        'journal_entry', to_jsonb(v_entry)
    );
end;
$$;


-- ----------------------------------------------------------------------------
-- 5. Grants — RPCs are backend/service-role only
-- ----------------------------------------------------------------------------
revoke all on function confirm_note_item(uuid, timestamptz) from public, anon, authenticated;
grant execute on function confirm_note_item(uuid, timestamptz) to service_role;

revoke all on function confirm_journal_item(uuid, timestamptz) from public, anon, authenticated;
grant execute on function confirm_journal_item(uuid, timestamptz) to service_role;
