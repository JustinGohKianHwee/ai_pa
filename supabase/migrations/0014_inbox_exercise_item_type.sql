-- ============================================================================
-- Migration 0014 — allow 'exercise' as an inbox_items.item_type (Phase 18 fix)
-- ============================================================================
-- Phase 18 added the 'exercise' classifier type and the exercise_logs module, but
-- inbox_items.item_type still carried the original CHECK constraint from migration
-- 0001, which did NOT include 'exercise'. Classifying a workout therefore produced
-- a constraint violation (postgrest APIError) when writing the inbox item, so the
-- item was flipped to needs_manual_classification instead of becoming an exercise
-- item. This widens the constraint to include 'exercise'.
--
-- The constraint name is Postgres's default for the inline column check in 0001
-- (<table>_<column>_check). Drop-if-exists then re-add keeps this idempotent.
-- ============================================================================

alter table inbox_items drop constraint if exists inbox_items_item_type_check;

alter table inbox_items add constraint inbox_items_item_type_check
    check (item_type in (
        'task',
        'finance',
        'calendar',
        'food',
        'exercise',
        'investment',
        'note',
        'journal',
        'unknown'
    ));
