-- ============================================================================
-- Migration 0005 — UNIQUE constraints for duplicate prevention
-- ============================================================================
-- 1. capture_events(source, source_message_id): prevents duplicate capture rows
--    from concurrent Telegram retries. The application-layer pre-check is the
--    common path (optimization); this constraint is the correctness guarantee
--    for the race window.
--
-- 2. inbox_items(capture_event_id): prevents two concurrent requests from both
--    inserting an inbox row for the same capture (e.g. the losing retry inserts
--    a recovery stub just before the winning request inserts its own row).
--
-- No existing duplicates are expected. If any exist, the relevant ALTER will
-- fail with a unique_violation — resolve them in the Supabase SQL Editor first.
-- ============================================================================

ALTER TABLE capture_events
  ADD CONSTRAINT capture_events_source_message_id_unique
  UNIQUE (source, source_message_id);

ALTER TABLE inbox_items
  ADD CONSTRAINT inbox_items_capture_event_id_unique
  UNIQUE (capture_event_id);
