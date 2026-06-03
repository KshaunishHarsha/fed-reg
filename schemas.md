-- ============================================================
-- Federal Register Sentinel — Supabase Schema
-- Full system schema owned and defined in phase_1/schema.sql
-- Phase 1 writes: documents (INGESTED state), filter_audit
-- Phase 2 writes: summaries, documents.pipeline_state → SUMMARY_GENERATED
-- Phase 3 writes: documents.pipeline_state → DIGEST_SENT
-- ============================================================


-- ============================================================
-- TABLE 1: documents
-- Core government metadata from the Federal Register API +
-- Phase 1 filtering flags. No LLM-generated text lives here.
-- ============================================================

CREATE TABLE documents (
    -- Government identity (from API)
    document_number     TEXT PRIMARY KEY,
    title               TEXT NOT NULL,
    abstract            TEXT,
    agency_names        TEXT[],
    document_type       TEXT,               -- raw type string from API response
    type                TEXT,               -- RULE | PRORULE | NOTICE
    subtype             TEXT,               -- e.g. executive order subtype
    page_length         INTEGER,
    html_url            TEXT,
    pdf_url             TEXT,
    comment_url         TEXT,
    comments_close_on   DATE,               -- from API: comment deadline
    effective_on        DATE,               -- from API: effective date
    significant         BOOLEAN,
    publication_date    DATE NOT NULL,

    -- Phase 1 filtering outputs
    confidence          TEXT CHECK (confidence IN ('HIGH', 'NEEDS_CONFIRMATION')),
    is_relevant         BOOLEAN,
    regulation_category TEXT CHECK (regulation_category IN (
                            'Proposed Rule', 'Final Rule', 'Notice', 'Other'
                        )),
    filter_reason       TEXT,               -- one-sentence AI explanation
    context_block       TEXT,               -- assembled by Layer 2a for docs without abstract

    -- Pipeline lifecycle (updated by each phase on completion)
    pipeline_state      TEXT NOT NULL DEFAULT 'INGESTED'
                        CHECK (pipeline_state IN (
                            'INGESTED',             -- Phase 1 complete
                            'SUMMARY_GENERATED',    -- Phase 2 complete
                            'DIGEST_SENT'           -- Phase 3 complete
                        )),

    created_at          TIMESTAMPTZ DEFAULT now(),
    updated_at          TIMESTAMPTZ DEFAULT now()
);

-- Index for the Phase 3 morning query (publication_date + pipeline_state)
CREATE INDEX idx_documents_date_state
    ON documents (publication_date, pipeline_state);

-- Index for Phase 2 read interface
CREATE INDEX idx_documents_relevant
    ON documents (is_relevant, publication_date);


-- ============================================================
-- TABLE 2: summaries
-- Phase 2 LLM output cache. One-to-one with documents.
-- Existence of a row = document has already been summarized.
-- Phase 2 checks this before every OpenAI call.
-- ============================================================

CREATE TABLE summaries (
    document_number     TEXT PRIMARY KEY
                        REFERENCES documents(document_number) ON DELETE CASCADE,
    xml_summary_blob    TEXT NOT NULL,      -- exact Phase 2 XML output
    created_at          TIMESTAMPTZ DEFAULT now(),
    updated_at          TIMESTAMPTZ DEFAULT now()
);


-- ============================================================
-- TABLE 3: filter_audit
-- Immutable log of every Phase 1 Layer 3 decision.
-- Never updated, only appended. Used to detect keyword drift
-- and AI behavior changes over time.
-- ============================================================

CREATE TABLE filter_audit (
    id                  BIGSERIAL PRIMARY KEY,
    document_number     TEXT NOT NULL,
    title               TEXT,
    layer2_confidence   TEXT,
    layer2_score        INTEGER,            -- context term match count
    layer3_decision     BOOLEAN,            -- true = kept, false = dropped
    layer3_reason       TEXT,               -- one-sentence AI explanation
    was_cached          BOOLEAN DEFAULT false,
    run_date            DATE NOT NULL,
    created_at          TIMESTAMPTZ DEFAULT now()
);

-- Index for audit review queries by date
CREATE INDEX idx_filter_audit_run_date
    ON filter_audit (run_date);

CREATE INDEX idx_filter_audit_document
    ON filter_audit (document_number);


-- ============================================================
-- FUNCTION: auto-update updated_at on row change
-- Apply to documents and summaries tables
-- ============================================================

CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_documents_updated_at
    BEFORE UPDATE ON documents
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER trg_summaries_updated_at
    BEFORE UPDATE ON summaries
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();


-- ============================================================
-- PHASE 3 MORNING QUERY (reference — not executed here)
-- Run at 7:30 AM to compile the daily digest
-- ============================================================

-- SELECT
--     d.document_number,
--     d.title,
--     d.agency_names,
--     d.type,
--     d.regulation_category,
--     d.comments_close_on,
--     d.effective_on,
--     d.html_url,
--     d.comment_url,
--     d.publication_date,
--     s.xml_summary_blob
-- FROM documents d
-- INNER JOIN summaries s ON d.document_number = s.document_number
-- WHERE d.pipeline_state = 'SUMMARY_GENERATED'
--   AND d.publication_date = CURRENT_DATE
-- ORDER BY
--     CASE d.type
--         WHEN 'PRORULE' THEN 1   -- Section A: proposed rules with comment periods
--         WHEN 'RULE'    THEN 2   -- Section B: final rules
--         WHEN 'NOTICE'  THEN 3   -- Section B: notices
--         ELSE                4   -- Section C: anything else
--     END,
--     d.comments_close_on ASC NULLS LAST;