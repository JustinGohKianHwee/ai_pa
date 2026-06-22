-- Phase 15a: deny direct anon/authenticated access to all personal data.
-- The FastAPI backend continues to use the service_role key, which has BYPASSRLS.

alter table capture_events enable row level security;
alter table capture_events force row level security;
revoke all on table capture_events from anon, authenticated;

alter table inbox_items enable row level security;
alter table inbox_items force row level security;
revoke all on table inbox_items from anon, authenticated;

alter table agent_runs enable row level security;
alter table agent_runs force row level security;
revoke all on table agent_runs from anon, authenticated;

alter table tasks enable row level security;
alter table tasks force row level security;
revoke all on table tasks from anon, authenticated;

alter table money_events enable row level security;
alter table money_events force row level security;
revoke all on table money_events from anon, authenticated;

alter table food_logs enable row level security;
alter table food_logs force row level security;
revoke all on table food_logs from anon, authenticated;

alter table calendar_intents enable row level security;
alter table calendar_intents force row level security;
revoke all on table calendar_intents from anon, authenticated;

revoke all on function confirm_task_item(uuid, timestamptz) from public, anon, authenticated;
grant execute on function confirm_task_item(uuid, timestamptz) to service_role;

revoke all on function confirm_finance_item(uuid, timestamptz) from public, anon, authenticated;
grant execute on function confirm_finance_item(uuid, timestamptz) to service_role;

revoke all on function confirm_food_item(uuid, timestamptz) from public, anon, authenticated;
grant execute on function confirm_food_item(uuid, timestamptz) to service_role;

revoke all on function confirm_calendar_item(uuid, timestamptz) from public, anon, authenticated;
grant execute on function confirm_calendar_item(uuid, timestamptz) to service_role;
