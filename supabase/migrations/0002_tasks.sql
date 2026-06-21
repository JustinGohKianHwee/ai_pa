-- ============================================================================
-- Migration 0002 — Tasks domain module (Phase 8)
-- ============================================================================
-- The first domain table and the first atomic confirm-plus-domain-record write.
--
-- Pipeline reminder:
--     capture → classify/extract → pending inbox → review → atomic confirm + domain
--
-- Phase 8 adds:
--   1. tasks               — confirmed action items, one per source inbox_item
--   2. confirm_task_item() — RPC that, in ONE transaction, creates exactly one
--                            task and flips the linked inbox_item to confirmed
--
-- Invariants this migration preserves:
--   * One inbox_item produces at most one task (UNIQUE inbox_item_id).
--   * A task and its inbox_item's confirmed state are written together or not at
--     all (single-statement PL/pgSQL function = single transaction).
--   * There is never a visible state where a task exists while its inbox_item is
--     still pending.
--   * Items confirmed before Phase 8 (no task row) are NOT backfilled.
--
-- NOT in this migration (deferred by design):
--   * Other domain tables (money_events, food_logs, ...) — per-module, later.
--   * Row Level Security / auth — Phase 15. No user_id column yet (single-user).
--   * Task editing, subtasks, recurrence, priority — out of Phase 8 scope.
--
-- urgency values match the canonical Phase 6 classifier schema
-- (TaskStructuredJson): today / this_week / someday, or NULL. 'this_month' is
-- intentionally NOT allowed — the classifier and the edit endpoint can never
-- produce it, so it would be a dead value.
-- ============================================================================


-- ----------------------------------------------------------------------------
-- tasks — confirmed action items
-- ----------------------------------------------------------------------------
create table if not exists tasks (
    id            uuid primary key default gen_random_uuid(),
    inbox_item_id uuid not null unique references inbox_items (id),
    title         text not null,
    urgency       text
        check (urgency is null or urgency in ('today', 'this_week', 'someday')),
    due_date      text,
    notes         text,
    status        text not null default 'open'
        check (status in ('open', 'completed')),
    completed_at  timestamptz,
    created_at    timestamptz not null default now(),
    updated_at    timestamptz not null default now(),
    check (
        (status = 'open' and completed_at is null)
        or
        (status = 'completed' and completed_at is not null)
    )
);

comment on table  tasks is
    'Confirmed action items. Exactly one row per source inbox_item (UNIQUE inbox_item_id). Written only by confirm_task_item() in the same transaction that confirms the inbox_item.';
comment on column tasks.inbox_item_id is
    'The reviewed inbox_item this task was confirmed from. UNIQUE — one task per item.';
comment on column tasks.title is
    'Task description. Sourced from inbox_items.title (canonical), which the backend requires to be non-empty before confirming.';
comment on column tasks.urgency is
    'Urgency tier from the classifier: today / this_week / someday, or null. Matches TaskStructuredJson.';
comment on column tasks.due_date is
    'Free-text due date exactly as extracted by the AI (e.g. "next Friday"). Stored as text — not parsed in Phase 8.';
comment on column tasks.status is
    'open or completed. Tasks are completed from the /tasks view; they are never edited after confirmation in Phase 8.';
comment on column tasks.completed_at is
    'When the task was marked complete (null while open). CHECK ties it to status.';


-- ----------------------------------------------------------------------------
-- updated_at maintenance for tasks
-- ----------------------------------------------------------------------------
-- Reuse the set_updated_at() trigger function created in migration 0001.
drop trigger if exists trg_tasks_set_updated_at on tasks;
create trigger trg_tasks_set_updated_at
    before update on tasks
    for each row
    execute function set_updated_at();


-- ----------------------------------------------------------------------------
-- Indexes
-- ----------------------------------------------------------------------------
-- The /tasks view filters by status and orders by created_at. UNIQUE on
-- inbox_item_id already provides an index for the confirmation lookup.
create index if not exists idx_tasks_status     on tasks (status);
create index if not exists idx_tasks_created_at on tasks (created_at);


-- ----------------------------------------------------------------------------
-- confirm_task_item — atomic confirmation RPC
-- ----------------------------------------------------------------------------
-- Creates exactly one task for a pending task-type inbox_item and flips that
-- item to confirmed, in one transaction. Returns { inbox_item, task } as JSON.
--
-- Atomicity: a PL/pgSQL function invoked as a single statement runs inside one
-- transaction. Any RAISE aborts and rolls back every write in the function.
--
-- Idempotency:
--   * UNIQUE (inbox_item_id) means a racing second insert cannot create a
--     duplicate task.
--   * If the item is already confirmed WITH a task, the existing pair is
--     returned (no second task).
--   * If the item is already confirmed WITHOUT a task (a Phase 7 legacy
--     confirm), it is NOT backfilled — the function raises instead.
--
-- Concurrency: SELECT ... FOR UPDATE locks the inbox row, serialising parallel
-- confirms. The second caller re-reads a confirmed row and returns the existing
-- task. At most one task is ever created.
--
-- The p_expected_updated_at guard rejects a confirm built on a stale read (an
-- edit landed between the backend's validation fetch and this call).
-- ----------------------------------------------------------------------------
create or replace function confirm_task_item(
    p_inbox_id uuid,
    p_expected_updated_at timestamptz default null
)
returns jsonb
language plpgsql
as $$
declare
    v_item inbox_items%rowtype;
    v_task tasks%rowtype;
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
        select * into v_task from tasks where inbox_item_id = p_inbox_id;
        if found then
            -- Already confirmed and a task exists → return the existing pair.
            return jsonb_build_object(
                'inbox_item', to_jsonb(v_item),
                'task', to_jsonb(v_task)
            );
        end if;
        -- Confirmed in a prior phase with no task → do NOT backfill.
        raise exception 'confirmed_without_task: %', p_inbox_id
            using errcode = 'P0003';
    end if;

    -- 4. Must be pending to proceed.
    if v_item.review_status <> 'pending' then
        raise exception 'inbox_item_not_pending: % (%)', p_inbox_id, v_item.review_status
            using errcode = 'P0004';
    end if;

    -- 5. Must be a task.
    if v_item.item_type <> 'task' then
        raise exception 'inbox_item_not_task: % (%)', p_inbox_id, v_item.item_type
            using errcode = 'P0005';
    end if;

    -- 6. Concurrency guard: reject a confirm built on a stale read.
    if p_expected_updated_at is not null and v_item.updated_at <> p_expected_updated_at then
        raise exception 'inbox_item_stale: %', p_inbox_id
            using errcode = 'P0006';
    end if;

    -- 7. Create exactly one task. UNIQUE (inbox_item_id) backstops a race.
    insert into tasks (inbox_item_id, title, urgency, due_date, notes)
    values (
        v_item.id,
        v_item.title,
        nullif(v_item.structured_json->>'urgency', ''),
        nullif(v_item.structured_json->>'due_date', ''),
        nullif(v_item.structured_json->>'notes', '')
    )
    returning * into v_task;

    -- 8. Confirm the inbox item using database UTC time.
    update inbox_items
       set review_status = 'confirmed',
           reviewed_at   = now()
     where id = p_inbox_id
    returning * into v_item;

    -- 9. Return both records.
    return jsonb_build_object(
        'inbox_item', to_jsonb(v_item),
        'task', to_jsonb(v_task)
    );
end;
$$;

-- RPC is backend/service-role only — never callable from the browser.
revoke all on function confirm_task_item(uuid, timestamptz) from public;
revoke all on function confirm_task_item(uuid, timestamptz) from anon;
revoke all on function confirm_task_item(uuid, timestamptz) from authenticated;
grant execute on function confirm_task_item(uuid, timestamptz) to service_role;
