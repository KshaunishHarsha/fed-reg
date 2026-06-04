-- ============================================================
-- Federal Register Sentinel — Full System Schema
-- Phase 1 writes: documents (INGESTED), filter_audit
-- Phase 2 writes: summaries, documents.pipeline_state → SUMMARY_GENERATED | SUMMARIZATION_FAILED
-- Phase 3 writes: documents.pipeline_state → DIGEST_SENT
-- ============================================================


-- TABLE 1: documents
CREATE TABLE documents (
    document_number     TEXT PRIMARY KEY,
    title               TEXT NOT NULL,
    abstract            TEXT,
    agency_names        TEXT[],
    document_type       TEXT,
    type                TEXT,
    subtype             TEXT,
    page_length         INTEGER,
    html_url            TEXT,
    pdf_url             TEXT,
    comment_url         TEXT,
    comments_close_on   DATE,
    effective_on        DATE,
    significant         BOOLEAN,
    publication_date    DATE NOT NULL,

    confidence          TEXT CHECK (confidence IN ('HIGH', 'NEEDS_CONFIRMATION')),
    is_relevant         BOOLEAN,
    regulation_category TEXT CHECK (regulation_category IN (
                            'Proposed Rule', 'Final Rule', 'Notice', 'Other'
                        )),
    filter_reason       TEXT,
    context_block       TEXT,

    pipeline_state      TEXT NOT NULL DEFAULT 'INGESTED'
                        CHECK (pipeline_state IN (
                            'INGESTED',
                            'SUMMARY_GENERATED',
                            'SUMMARIZATION_FAILED',
                            'DIGEST_SENT'
                        )),

    created_at          TIMESTAMPTZ DEFAULT now(),
    updated_at          TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_documents_date_state
    ON documents (publication_date, pipeline_state);

CREATE INDEX idx_documents_relevant
    ON documents (is_relevant, publication_date);


-- TABLE 2: summaries (Phase 2 owned)
-- summarization_tier:    1 = abstract, 2 = pruned HTML, 3 = context_block
-- summarization_status:  pending | complete | failed
-- correction_attempts:   incremented each time Phase 3 requests a correction
CREATE TABLE summaries (
    document_number         TEXT PRIMARY KEY
                            REFERENCES documents(document_number) ON DELETE CASCADE,
    xml_summary_blob        TEXT NOT NULL,
    summarization_tier      INTEGER,
    summarization_status    TEXT NOT NULL DEFAULT 'pending'
                            CHECK (summarization_status IN ('pending', 'complete', 'failed')),
    correction_attempts     INTEGER NOT NULL DEFAULT 0,
    created_at              TIMESTAMPTZ DEFAULT now(),
    updated_at              TIMESTAMPTZ DEFAULT now()
);


-- TABLE 3: filter_audit
-- No foreign key to documents intentionally — logs discarded documents too
CREATE TABLE filter_audit (
    id                  BIGSERIAL PRIMARY KEY,
    document_number     TEXT NOT NULL,
    title               TEXT,
    layer2_confidence   TEXT,
    layer2_score        INTEGER,
    layer3_decision     BOOLEAN,
    layer3_reason       TEXT,
    was_cached          BOOLEAN DEFAULT false,
    run_date            DATE NOT NULL,
    created_at          TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_filter_audit_run_date ON filter_audit (run_date);
CREATE INDEX idx_filter_audit_document ON filter_audit (document_number);


-- auto-update updated_at triggers
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
-- PHASE 3 MORNING QUERY (reference)
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
--         WHEN 'PRORULE' THEN 1
--         WHEN 'RULE'    THEN 2
--         WHEN 'NOTICE'  THEN 3
--         ELSE                4
--     END,
--     d.comments_close_on ASC NULLS LAST;