-- Replace <OWNER_USER_ID> with your Supabase owner UUID before running.
-- Phase 15b: add the single-owner contract to every pre-portfolio table.

alter table capture_events add column if not exists owner_id text;
update capture_events set owner_id = '<OWNER_USER_ID>' where owner_id is null;
alter table capture_events alter column owner_id set default '<OWNER_USER_ID>';
alter table capture_events alter column owner_id set not null;

alter table inbox_items add column if not exists owner_id text;
update inbox_items set owner_id = '<OWNER_USER_ID>' where owner_id is null;
alter table inbox_items alter column owner_id set default '<OWNER_USER_ID>';
alter table inbox_items alter column owner_id set not null;

alter table agent_runs add column if not exists owner_id text;
update agent_runs set owner_id = '<OWNER_USER_ID>' where owner_id is null;
alter table agent_runs alter column owner_id set default '<OWNER_USER_ID>';
alter table agent_runs alter column owner_id set not null;

alter table tasks add column if not exists owner_id text;
update tasks set owner_id = '<OWNER_USER_ID>' where owner_id is null;
alter table tasks alter column owner_id set default '<OWNER_USER_ID>';
alter table tasks alter column owner_id set not null;

alter table money_events add column if not exists owner_id text;
update money_events set owner_id = '<OWNER_USER_ID>' where owner_id is null;
alter table money_events alter column owner_id set default '<OWNER_USER_ID>';
alter table money_events alter column owner_id set not null;

alter table food_logs add column if not exists owner_id text;
update food_logs set owner_id = '<OWNER_USER_ID>' where owner_id is null;
alter table food_logs alter column owner_id set default '<OWNER_USER_ID>';
alter table food_logs alter column owner_id set not null;

alter table calendar_intents add column if not exists owner_id text;
update calendar_intents set owner_id = '<OWNER_USER_ID>' where owner_id is null;
alter table calendar_intents alter column owner_id set default '<OWNER_USER_ID>';
alter table calendar_intents alter column owner_id set not null;
