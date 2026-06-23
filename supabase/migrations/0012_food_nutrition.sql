-- Phase 17: food calories/macros + photo capture.
-- Extends food_logs with nutrition + an image reference, adds an image path to
-- capture_events (the raw photo, parallel to audio_file_id), and extends
-- confirm_food_item to persist nutrition (from structured_json) + the image (from
-- the linked capture event), preserving the Phase 11/15b behaviour exactly.

alter table food_logs add column if not exists calories  numeric;
alter table food_logs add column if not exists protein_g numeric;
alter table food_logs add column if not exists carbs_g   numeric;
alter table food_logs add column if not exists fat_g     numeric;
alter table food_logs add column if not exists image_path text;

alter table capture_events add column if not exists image_path text;

create or replace function confirm_food_item(
    p_inbox_id uuid,
    p_expected_updated_at timestamptz default null
)
returns jsonb
language plpgsql
as $$
declare
    v_item       inbox_items%rowtype;
    v_log        food_logs%rowtype;
    v_image_path text;
begin
    select * into v_item from inbox_items where id = p_inbox_id for update;

    if not found then
        raise exception 'inbox_item_not_found: %', p_inbox_id using errcode = 'P0002';
    end if;

    if v_item.review_status = 'confirmed' then
        select * into v_log from food_logs where inbox_item_id = p_inbox_id;
        if found then
            return jsonb_build_object(
                'inbox_item', to_jsonb(v_item),
                'food_log',   to_jsonb(v_log)
            );
        end if;
        raise exception 'confirmed_without_food_log: %', p_inbox_id using errcode = 'P0003';
    end if;

    if v_item.review_status <> 'pending' then
        raise exception 'inbox_item_not_pending: % (%)', p_inbox_id, v_item.review_status
            using errcode = 'P0004';
    end if;

    if v_item.item_type <> 'food' then
        raise exception 'inbox_item_not_food: % (%)', p_inbox_id, v_item.item_type
            using errcode = 'P0005';
    end if;

    if p_expected_updated_at is not null and v_item.updated_at <> p_expected_updated_at then
        raise exception 'inbox_item_stale: %', p_inbox_id using errcode = 'P0006';
    end if;

    -- The photo (if any) is the raw capture; carry its storage path onto the food log.
    select image_path into v_image_path
      from capture_events
     where id = v_item.capture_event_id;

    insert into food_logs (
        inbox_item_id, description, meal_type, logged_at,
        calories, protein_g, carbs_g, fat_g, image_path
    )
    values (
        v_item.id,
        v_item.structured_json->>'description',
        nullif(v_item.structured_json->>'meal_type', ''),
        nullif(v_item.structured_json->>'logged_at', ''),
        (v_item.structured_json->>'calories')::numeric,
        (v_item.structured_json->>'protein_g')::numeric,
        (v_item.structured_json->>'carbs_g')::numeric,
        (v_item.structured_json->>'fat_g')::numeric,
        v_image_path
    )
    returning * into v_log;

    update inbox_items
       set review_status = 'confirmed',
           reviewed_at   = now()
     where id = p_inbox_id
    returning * into v_item;

    insert into memory_events (
        domain, event_type, payload_json, source_table, source_id, occurred_at
    )
    values (
        'food',
        'confirmed',
        jsonb_build_object(
            'description', v_log.description,
            'meal_type',   v_log.meal_type,
            'calories',    v_log.calories,
            'logged_at',   v_log.logged_at
        ),
        'food_logs',
        v_log.id,
        now()
    );

    return jsonb_build_object(
        'inbox_item', to_jsonb(v_item),
        'food_log',   to_jsonb(v_log)
    );
end;
$$;

revoke all on function confirm_food_item(uuid, timestamptz) from public, anon, authenticated;
grant execute on function confirm_food_item(uuid, timestamptz) to service_role;
