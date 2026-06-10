# CLAUDE.md — Phase 3 AI Assistant Context

This file gives AI coding assistants (Claude, Gemini, Copilot, etc.) the context
they need to work correctly inside `phase_3/` without violating team contracts or
causing git conflicts with the Phase 1 / Phase 2 contributors.

---

## Project Context

**Project:** Federal Register Sentinel — Open Paws / Animal Legal Defense Fund  
**This folder:** Phase 3 — Post-Processing and Email Delivery  
**Your contributor:** Working on Phase 3 only.

The codebase is split across three phases owned by different contributors:
- `phase_1/` — ingestion and filtering (partner's code — do not touch)
- `phase_2/` — LLM summarization (partner's code — do not touch)
- `phase_3/` — validation, persistence, digest compilation, email (your code)

> **Rule #1: Never modify files outside `phase_3/` without explicitly being asked.**
> The exceptions are: `schemas.md`, `.env.example`, and `phase_1/schema.sql`
> (schema additions only — never modify existing columns or constraints).

---

## Architecture Overview

Phase 3 is a **FastAPI** service. It has no LLM calls of its own. It receives XML
from Phase 2, validates it, caches it to Supabase, compiles a daily email digest,
and hands it off.

```
Phase 2 POST /phase3/ingest
        │
        ▼
  validator.py  ──(fail)──▶  PHASE2_CORRECTION_URL (HTTP POST back to Phase 2)
        │ (pass)
        ▼
  persistence.py  ──▶  documents.pipeline_state = 'DIGEST_SENT'
        │
        ▼  (triggered by POST /phase3/run — daily cron)
  digest_query.py  ──▶  SELECT SUMMARY_GENERATED docs for today
        │
        ▼
  digest_builder.py  ──▶  section A/B/C sort  ──▶  Jinja2 render
        │
        ▼
  DigestPackage (html_body + text_body)
        │
        ▼
  [TODO: platform_handoff.py — Step 4 not yet implemented]
```

---

## Key Files

| File | Role | Status |
|---|---|---|
| `router.py` | All endpoints | ✅ Complete |
| `models.py` | Pydantic models (IngestPayload, DocumentRecord, ValidatedSummary) | ✅ Complete |
| `validator.py` | XML field validation + URL stripping | ✅ Complete |
| `xml_parser.py` | ElementTree parse of `xml_summary_blob` | ✅ Complete |
| `persistence.py` | Idempotent `pipeline_state` promotion | ✅ Complete |
| `db.py` | SQLAlchemy async engine + session factory | ✅ Complete |
| `digest_query.py` | Async DB query for today's SUMMARY_GENERATED docs | ✅ Complete |
| `digest_builder.py` | Section A/B/C classification + Jinja2 rendering | ✅ Complete |
| `templates/digest_email.html` | Rich HTML email | ✅ Complete |
| `templates/digest_email.txt` | Plain-text fallback | ✅ Complete |
| `templates/zero_result.html` | Circuit-breaker HTML (no docs day) | ✅ Complete |
| `templates/zero_result.txt` | Circuit-breaker plain-text | ✅ Complete |
| `platform_handoff.py` | Open Paws email delivery | ⏳ Step 4 — not yet started |

---

## Active Endpoints

```
POST /phase3/run              ← CRON ENTRY POINT: calls Phase1 → Phase2 → builds digest
POST /phase3/ingest           ← called by Phase 2 per document
GET  /phase3/status/{doc_num} ← check pipeline_state
POST /phase3/digest/test      ← [DEV ONLY] compile email from existing DB rows
POST /phase3/validate/test    ← [DEV ONLY] validate raw XML blob
```

---

## Database Contract

**Phase 3 reads from:**
- `documents` table: `document_number`, `title`, `agency_names`, `type`,
  `regulation_category`, `confidence`, `comments_close_on`, `effective_on`,
  `html_url`, `comment_url`, `publication_date`, `pipeline_state`
- `summaries` table: `xml_summary_blob`

**Phase 3 writes:**
- `documents.pipeline_state` → `'DIGEST_SENT'` (only column, only table)

**Phase 3 never:**
- Creates new tables or columns
- Writes to the `summaries` table
- Modifies `schemas.md` or `phase_1/schema.sql` (except with explicit user approval)

The schema is in `phase_1/schema.sql` — run once in Supabase SQL Editor to set up
all three tables (`documents`, `summaries`, `filter_audit`).

---

## Phase 2 Integration Contract

Phase 2 must `POST /phase3/ingest` with this JSON structure:

```json
{
  "document_record": {
    "document_number": "2026-09841",
    "title": "Proposed welfare standards for commercial pig farming",
    "agency_names": ["USDA", "APHIS"],
    "type": "PRORULE",
    "regulation_category": "Proposed Rule",
    "comments_close_on": "2026-07-15",
    "effective_on": null,
    "html_url": "https://www.federalregister.gov/d/2026-09841",
    "comment_url": "APHIS-2026-0041",
    "publication_date": "2026-06-04",
    "confidence": "HIGH",
    "pipeline_state": "SUMMARY_GENERATED"
  },
  "xml_summary_blob": "<regulatory_document_summary>...</regulatory_document_summary>"
}
```

The `xml_summary_blob` must conform exactly to the schema in `llm_output_contract.md`.

**Correction flow:** If validation fails, Phase 3 posts to `PHASE2_CORRECTION_URL`:
```json
{ "document_number": "2026-09841", "error_detail": "plain_language_summary has 5 sentences; maximum is 3." }
```
Phase 2 re-runs the LLM with this error as a system correction note. Max 2 retries.

---

## Section Classification (digest_builder.py)

Two independent axes. **Section** (action) is driven only by `type` + comment window:

| Condition | Section |
|---|---|
| `type=PRORULE` + `comments_close_on >= today` | **A** — Action Required |
| everything else (RULE, NOTICE, expired PRORULE, PRESDOC, unknown) | **B** — Regulatory Tracking |

Section C was removed (2026-06-10). Its plumbing (`_section_c`, `section_c_count`, template block) stays but is always empty.

**Relevancy** (confidence) is a separate axis: the `confidence` column now holds `HIGH` / `MEDIUM` / `LOW`, rendered as a per-card badge and used to sort within each section. `_normalize_relevancy()` maps legacy `NEEDS_CONFIRMATION` → `LOW`.

---

## Static Link Rules (CRITICAL — never break this)

All outbound links in the email are built from database columns only.
The LLM **must not** produce any URLs. Validator strips them silently if detected.

- **Source URL:** `https://www.federalregister.gov/d/{document_number}`  
  Built in `digest_builder._build_source_url()` from `documents.document_number`.

- **Comment URL:** `https://www.regulations.gov/commentOn?D={comment_url}`  
  Built in `digest_builder._build_comment_url()` from `documents.comment_url`.  
  If `comment_url` already starts with `http`, it is used as-is.  
  If it looks like a docket ID (e.g. `APHIS-2026-0041`), it is interpolated.

---

## Environment Variables

```env
SUPABASE_URL=              # Supabase project REST URL
SUPABASE_KEY=              # Supabase anon or service key
DATABASE_URL=              # postgresql+asyncpg://postgres.[ref]:[pass]@...supabase.com:6543/postgres
OPENROUTER_API_KEY=        # LLM key (Phase 2 uses this)
PHASE1_RUN_URL=            # e.g. http://localhost:8001/phase1/run
PHASE2_RUN_URL=            # e.g. http://localhost:8002/phase2/run
PHASE2_CORRECTION_URL=     # e.g. http://localhost:8002/phase2/correct
```

---

## What is NOT Done Yet (Step 4)

`platform_handoff.py` — the final piece that takes the compiled `DigestPackage` and
sends it via the Open Paws email infrastructure. The `POST /phase3/run` endpoint already
has a `# TODO Step 4: pass package to platform_handoff.send_digest(package)` comment
in `router.py` marking the exact integration point.

Step 4 will need:
- Open Paws API endpoint URL + key (to be provided by project lead)
- Unsubscribe webhook handler at `POST /phase3/webhook/unsubscribe`

---

## Design Decisions to Preserve

1. **No ORM.** All DB access is raw SQL via `sqlalchemy.text()`. Keep it that way.
2. **No LLM calls in Phase 3.** If you are about to import an LLM client here, stop.
3. **No cross-phase imports.** Phase 3 never imports from `phase_1` or `phase_2`.
4. **Idempotency everywhere.** The pipeline can be re-run safely after a crash.
5. **Static links only.** Never interpolate LLM text into a URL. Ever.
6. **`DigestPackage` is a Pydantic model** (not a dataclass) — required for FastAPI
   `response_model` serialization. Do not revert it to a dataclass.
