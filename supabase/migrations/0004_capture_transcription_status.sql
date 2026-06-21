-- ============================================================================
-- Migration 0004 — Add transcription_failed to capture_events.processing_status
-- ============================================================================
-- Phase 10 (voice transcription) introduces a pipeline stage before classification.
-- Transcription failure is a distinct lifecycle state; reusing classification_failed
-- would be misleading in the agent_runs audit and in future observability tooling.
-- This migration widens the existing CHECK constraint additively.
-- No existing rows are affected (no rows have processing_status = 'transcription_failed').
--
-- The constraint name capture_events_processing_status_check is the PostgreSQL
-- auto-generated name for an inline CHECK on this column. DROP CONSTRAINT IF EXISTS
-- is used so the statement is safe even if Supabase assigned a slightly different name.
-- ============================================================================

ALTER TABLE capture_events
  DROP CONSTRAINT IF EXISTS capture_events_processing_status_check;

ALTER TABLE capture_events
  ADD CONSTRAINT capture_events_processing_status_check
  CHECK (processing_status IN (
    'received',
    'transcription_failed',
    'classified',
    'classification_failed',
    'invalid_ai_output'
  ));
