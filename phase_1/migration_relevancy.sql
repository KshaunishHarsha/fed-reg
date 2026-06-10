-- ============================================================
-- Migration: confidence column → HIGH / MEDIUM / LOW relevancy grade
-- Run once in the Railway SQL editor.
--
-- Before: confidence held the keyword tier ('HIGH' | 'NEEDS_CONFIRMATION').
-- After:  confidence holds the relevancy grade ('HIGH' | 'MEDIUM' | 'LOW').
--
-- Phase 1 now writes HIGH for strong anchor matches and the AI's MEDIUM/LOW
-- grade for context-only docs. Phase 3 renders this as a per-card relevancy
-- badge and no longer uses it for section A/B/C assignment.
-- ============================================================

BEGIN;

-- 1. Drop the old constraint (auto-named documents_confidence_check by Postgres).
ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_confidence_check;

-- 2. Convert any legacy values. NEEDS_CONFIRMATION was the weak keyword tier,
--    which maps to the lowest relevancy grade.
UPDATE documents SET confidence = 'LOW' WHERE confidence = 'NEEDS_CONFIRMATION';

-- 3. Re-add the constraint with the new allowed values.
ALTER TABLE documents
    ADD CONSTRAINT documents_confidence_check
    CHECK (confidence IN ('HIGH', 'MEDIUM', 'LOW'));

COMMIT;
