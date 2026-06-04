# Federal Register Sentinel — CLAUDE.md

> Single source of truth for the entire project. Read this before touching any code.
> **Rule: never modify files outside your assigned phase without explicit user approval.**

---

## Project

Automated regulatory monitoring tool for the **Animal Legal Defense Fund (ALDF)**, integrated into their **Open Paws** platform. Replaces manual daily Federal Register review by attorneys and policy staff.

Every morning the full system:
1. Pulls that day's Federal Register publications from 7 target agencies (Phase 1)
2. Filters to animal-relevant documents through a 4-layer keyword + AI pipeline (Phase 1)
3. Generates plain-language advocacy summaries via LLM (Phase 2)
4. Validates, classifies into digest sections, and emails a formatted daily digest (Phase 3)

---

## How to Run

```bash
# Install all dependencies
pip install -r requirements.txt

# Start the unified app (all phases, one process, port 8000)
python main.py

# Full pipeline run for today
curl -X POST http://localhost:8000/run

# Full pipeline run for a specific date (backfill / testing)
curl -X POST "http://localhost:8000/run?date=2025-01-14"

# Phase 1 standalone — dry-run (real FR API, no AI or DB writes)
cd phase_1 && python pipeline.py --dry-run --date 2025-01-14

# Full Phase 1 standalone run
cd phase_1 && python pipeline.py --date 2025-01-14

# Unit tests (no env vars required)
cd phase_1 && python -m pytest tests/ -v   # 43 tests
cd phase_2 && python -m pytest tests/ -v   # 69 tests
```

---

## Repository Structure

```
fed-reg/
├── .env                    # Real secrets — gitignored, root only
├── .env.example            # Template with all required keys
├── .gitignore
├── CLAUDE.md               # This file
├── main.py                 # Unified FastAPI app — single entry point, port 8000
├── orchestrator.py         # Phase 1 → 2 → 3 sequential orchestration (direct calls)
├── schema.sql              # Root-level schema reference
├── schemas.md              # DB schema documentation
├── build.md                # Original build spec — gitignored
├── brief.md                # Project brief — gitignored
├── project-plan.md         # Phase 2 build plan — gitignored
│
├── phase_1/                # Ingestion + filtering
│   ├── config.py           # All constants: agency slugs, keywords, thresholds, model
│   ├── models.py           # RawDocument → FilteredDocument → ConfirmedDocument
│   ├── ingestion.py        # Layer 1: FR API fetch + dedup
│   ├── keyword_filter.py   # Layer 2 + 2a: noise filter, keyword scoring, PDF scan
│   ├── ai_verification.py  # Layer 3: GPT-4o-mini via OpenRouter + instructor
│   ├── database.py         # supabase-py helpers (synchronous)
│   ├── pipeline.py         # CLI entry point: --date, --dry-run
│   ├── schema.sql          # Authoritative full-system DB schema (run once in Supabase)
│   ├── requirements.txt
│   └── tests/              # 43 tests
│
├── phase_2/                # LLM summarization
│   ├── models.py           # DocumentRecord (DB read), DocumentSummary (LLM output + validators)
│   ├── xml_builder.py      # Deterministic XML serialization — no LLM
│   ├── boilerplate_pruner.py # Tier 2: fetch body_html_url, strip noise sections
│   ├── tier_router.py      # Route by page_length → Tier 1 / 2 / 3
│   ├── summarizer.py       # GPT-4o-mini via OpenRouter, temp=0, instructor self-correct
│   ├── database.py         # Async SQLAlchemy raw SQL
│   ├── pipeline.py         # Orchestrator — accepts phase3_ingest_fn callback
│   ├── api.py              # APIRouter included in main.py
│   ├── requirements.txt
│   └── tests/              # 69 tests
│
└── phase_3/                # Validation, digest compilation, email delivery
    ├── router.py           # APIRouter — all Phase 3 endpoints
    ├── models.py           # IngestPayload, DocumentRecord, ValidatedSummary, ValidationResult
    ├── validator.py        # validate_blob(doc_number, xml_blob) → ValidationResult
    ├── xml_parser.py       # ElementTree parse of xml_summary_blob
    ├── persistence.py      # persist_validated_document(doc_number) — async, idempotent
    ├── db.py               # SQLAlchemy async engine + session factory
    ├── digest_query.py     # fetch_digest_rows(run_date) — async
    ├── digest_builder.py   # build_digest(rows, run_date) → DigestPackage — sync
    ├── mail_test.py        # SMTP send to test_recipients.yaml
    ├── platform_handoff.py # Step 4 — not yet implemented
    ├── llm_output_contract.md
    ├── schemas.md
    ├── test_recipients.yaml
    └── templates/          # digest_email.html/txt, zero_result.html/txt
```

---

## Environment Variables

`.env` lives at **repo root** only. Never create a `.env` inside a phase directory.

| Variable | Used By | Purpose |
|----------|---------|---------|
| `OPENROUTER_API_KEY` | Phase 1 `ai_verification.py`, Phase 2 `summarizer.py` | OpenRouter key → model `openai/gpt-4o-mini` |
| `SUPABASE_URL` | Phase 1 `database.py` | Supabase project REST URL (supabase-py client) |
| `SUPABASE_KEY` | Phase 1 `database.py` | Supabase anon or service role key |
| `DATABASE_URL` | Phase 2 `database.py`, Phase 3 `db.py` | `postgresql+asyncpg://...` — async SQLAlchemy direct Postgres |
| `SMTP_HOST` | Phase 3 `mail_test.py` | e.g. `smtp.gmail.com` |
| `SMTP_PORT` | Phase 3 `mail_test.py` | e.g. `465` (SSL) |
| `SMTP_USER` | Phase 3 `mail_test.py` | Gmail address / SMTP login |
| `SMTP_PASSWORD` | Phase 3 `mail_test.py` | Gmail App Password (16 chars) |
| `SMTP_FROM` | Phase 3 `mail_test.py` | Sender display string |

How each phase loads `.env`:
- Phase 1 + 2: `load_dotenv(Path(__file__).parent.parent / ".env")`
- Root files (`main.py`, `orchestrator.py`): `load_dotenv(Path(__file__).parent / ".env")`

No inter-phase HTTP URLs needed. All phases run in the same process via `orchestrator.py`.

> Phase 3's `router.py` also reads `PHASE1_RUN_URL`, `PHASE2_RUN_URL`, `PHASE2_CORRECTION_URL` for its
> own legacy `/phase3/run` endpoint. These are not needed when running through `POST /run`.

---

## Database

Authoritative schema: **`phase_1/schema.sql`** — run once in Supabase SQL Editor.

| Table | Writer | Purpose |
|-------|--------|---------|
| `documents` | Phase 1 creates; Phase 2 + 3 update `pipeline_state` | One row per FR document. PK: `document_number`. |
| `summaries` | Phase 2 | `xml_summary_blob`, `summarization_tier`, `summarization_status`, `correction_attempts`. FK → `documents`. |
| `filter_audit` | Phase 1 | Every Layer 3 AI decision logged here. No FK to documents (logs dropped docs too). |

**`pipeline_state` lifecycle:**

```
INGESTED               ← Phase 1 writes
    ↓
SUMMARY_GENERATED      ← Phase 2 writes on success
SUMMARIZATION_FAILED   ← Phase 2 writes on permanent LLM failure
    ↓
DIGEST_SENT            ← Phase 3 writes via persist_validated_document()
```

Phase 1 owns all writes to `documents` (except `pipeline_state`). Phase 2 owns all writes to `summaries`. Phase 3 only ever writes `pipeline_state = 'DIGEST_SENT'` on `documents`.

---

## System Architecture

**One process. One port (8000). All inter-phase calls are direct Python function calls — no HTTP between phases.**

```
POST /run  (main.py)
    └── orchestrator.run_full_pipeline(target_date)
            │
            ├─ Phase 1: phase_1.pipeline.run_pipeline(run_date)
            │       Runs in ThreadPoolExecutor (Phase 1 is synchronous)
            │       FR API → keyword filter → AI verification → documents table
            │       Returns List[ConfirmedDocument]
            │
            ├─ Phase 2: phase_2.pipeline.run_pipeline(phase3_ingest_fn=callback)
            │       Per document:
            │         tier_router → summarizer → xml_builder → summaries table
            │         → callback(doc, xml_blob)
            │               ├─ phase_3.validator.validate_blob(doc_num, xml_blob)
            │               │       Returns ValidationResult (.passed, .error_detail)
            │               ├─ phase_3.persistence.persist_validated_document(doc_num)
            │               │       Sets pipeline_state = DIGEST_SENT
            │               └─ on failure: phase_2.pipeline.handle_correction(doc_num, error)
            │                       Reruns LLM with correction note (max 2 retries)
            │
            └─ Phase 3 digest:
                    phase_3.digest_query.fetch_digest_rows(run_date)   [async]
                    phase_3.digest_builder.build_digest(rows, run_date) [sync]
                    → DigestPackage (html_body, text_body, section counts)
                    → TODO Step 4: platform_handoff.send_digest(package)
```

---

## All Endpoints (port 8000)

| Endpoint | Source | Purpose |
|----------|--------|---------|
| `POST /run?date=YYYY-MM-DD` | `main.py` → `orchestrator.py` | **Primary cron entry point.** Full Phase 1→2→3 in-process. |
| `GET /health` | `main.py` | Liveness check |
| `POST /phase2/run` | `phase_2/api.py` | Phase 2 standalone — no Phase 3 callback |
| `POST /phase2/correct` | `phase_2/api.py` | Correction hook — reruns LLM for one doc |
| `POST /phase3/run` | `phase_3/router.py` | Legacy cron path (calls Phase 1+2 via HTTP env vars — superseded by `POST /run`) |
| `POST /phase3/ingest` | `phase_3/router.py` | Per-document validate + persist |
| `GET /phase3/status/{doc_num}` | `phase_3/router.py` | Read `documents.pipeline_state` |
| `POST /phase3/digest/test` | `phase_3/router.py` | Dev — compile digest from existing DB rows |
| `POST /phase3/mail/test` | `phase_3/router.py` | Dev — compile + send via SMTP to `test_recipients.yaml` |
| `POST /phase3/validate/test` | `phase_3/router.py` | Dev — validate a raw XML blob in isolation |

---

## Build Status

| Component | Status | Notes |
|-----------|--------|-------|
| `main.py` + `orchestrator.py` | ✅ Complete | Unified app, direct in-process phase calls |
| **Phase 1** — Ingestion + Filtering | ✅ Complete | 43 tests passing |
| **Phase 2** — LLM Summarization | ✅ Complete | 69 tests passing |
| **Phase 3** — Validation, Digest, Email | ✅ Steps 1–3 complete | Step 4 (`platform_handoff.py`) not yet implemented |

---

## Phase 1 — Decisions and Quirks

### Filtering philosophy
False negatives (missing a relevant doc) are worse than false positives. All keyword thresholds and AI prompts are tuned toward inclusion.

### AI is last resort
GPT-4o-mini only sees documents that passed at least one keyword check. Controls cost and latency. Layer 2a (PDF scan) runs only when `abstract` is absent AND the doc passed scoring.

### OpenRouter routing
`ai_verification.py` uses the standard OpenAI SDK pointed at `https://openrouter.ai/api/v1` with `OPENROUTER_API_KEY`. No SDK changes needed — OpenRouter is API-compatible. Model string: `openai/gpt-4o-mini`.

### Idempotency via document_number
FR's `document_number` is the unique ID. It's the primary key everywhere. `is_already_processed()` checks before any AI call — safe to rerun after crashes.

### No date extraction from AI
`comments_close_on` and `effective_on` come directly from the FR API. `VerificationResult` has no date fields — prevents hallucinated dates.

### context_block stored in DB
Phase 2 Tier 3 (>50 page docs) reuses the `context_block` Phase 1 assembled. Avoids re-downloading PDFs.

### Supabase upsert uses ignore_duplicates
`save_confirmed_document()` → `upsert(..., ignore_duplicates=True)` = ON CONFLICT DO NOTHING. Never overwrites.

### Audit log has no FK to documents
`filter_audit` logs every doc reaching Layer 3, including those dropped (`is_relevant=False`). A FK would prevent logging drops.

### Pagination on published documents
`/documents.json` is paginated. `_fetch_published()` follows `next_page_url` until exhausted. After the first page, params are embedded in the URL so `params` is reset to `[]`.

### Federal Register API — confirmed quirks
- **`document_type` is rejected with 400.** Use `type` (machine-readable: `RULE`, `PRORULE`, `NOTICE`). `document_type` is excluded from `_FR_FIELDS` in `ingestion.py`.
- **Public inspection uses `/{date}.json`, not `/current.json`.** 404 on weekends and holidays — handled gracefully (returns empty list).
- **Public inspection has no server-side filtering.** Agency slug + type filtered client-side.
- `agencies` on published docs is a list of objects; `agency_names` is a flat list of strings.
- Public inspection docs may lack `abstract`, `page_length`, `comments_close_on` — all optional in `RawDocument`.
- Public inspection docs use `target_date` as `publication_date` (pre-publication).
- `PRESDOCU` excluded from `TARGET_DOC_TYPES` by design.

### Phase 2 read interface (only function Phase 2 should call on Phase 1's DB)
```python
# phase_1/database.py
get_confirmed_documents_for_date(run_date: date) -> List[dict]
# Returns all documents where is_relevant=True and publication_date=run_date
```

---

## Phase 2 — Decisions and Quirks

### Tier routing
| Tier | Condition | Text source |
|------|-----------|-------------|
| 1 | `page_length < 15` or `None` | `abstract` → fallback: `title` |
| 2 | `15 ≤ page_length ≤ 50` | `boilerplate_pruner.prune()` → fallback: `abstract` → `title` |
| 3 | `page_length > 50` | `context_block` from DB — **never re-fetch PDF** → fallback: `abstract` → `title` |

`summarization_tier` is written to `summaries` table on every row.

### Correction loop
1. Phase 3 validates XML blob after `POST /phase3/ingest`
2. On failure, Phase 3 posts `{document_number, error_detail}` to `POST /phase2/correct`
3. Phase 2 increments `summaries.correction_attempts`
4. If `correction_attempts ≤ 2`: reruns `process_document(doc, correction_note=error_detail)`
5. If `correction_attempts > 2`: sets `summarization_status = 'failed'` — does not POST to Phase 3 again

In the unified app, the orchestrator mediates this loop directly via the `phase3_ingest_fn` callback without any HTTP calls.

### Phase 3 delivery payload
```json
{
  "document_record": {
    "document_number": "2025-00467",
    "title": "...",
    "agency_names": ["Fish and Wildlife Service"],
    "type": "RULE",
    "regulation_category": "Final Rule",
    "confidence": "HIGH",
    "comments_close_on": "2025-03-17",
    "effective_on": null,
    "html_url": "https://www.federalregister.gov/d/2025-00467",
    "comment_url": "FWS-2025-0001",
    "publication_date": "2025-01-14",
    "pipeline_state": "SUMMARY_GENERATED"
  },
  "xml_summary_blob": "<regulatory_document_summary>...</regulatory_document_summary>"
}
```

### No ORM
All DB access via `sqlalchemy.text()` raw SQL. Module-level `_engine` singleton (lazy-initialized).

### Disclaimer is always hardcoded
`models.py` validator overwrites `disclaimer` with the `DISCLAIMER` constant regardless of LLM output. Never trust LLM output for this field.

### Prompt injection prevention
Document content is wrapped in `<document_payload>...</document_payload>` tags before the LLM call. URLs are stripped from the text first.

### Temperature 0
All LLM calls use `temperature=0` for deterministic, auditable output.

### Public inspection date handling
`doc.is_public_inspection` is inferred: `True` when `abstract is None`. System prompt instructs the model not to infer or calculate date fields for these docs.

### Two separate self-correction loops
- **instructor self-correction** (max 2 retries): catches Pydantic validation failures on the raw LLM response (word count, list length, etc.) within a single `summarize()` call.
- **Phase 3 correction** (max 2 retries): catches semantic/structural failures detected by Phase 3's XML validator after delivery. Each retry increments `correction_attempts` in the DB.

### Boilerplate pruner fetches body_html_url per Tier 2 call
Phase 1 doesn't store `body_html_url`. For every Tier 2 doc, `boilerplate_pruner.py` makes one additional FR API call: `GET /api/v1/documents/{doc_num}.json?fields[]=body_html_url`.

---

## Phase 3 — Decisions and Quirks

### Validation rules (what Phase 2's XML must satisfy)
From `phase_3/models.py` — `ValidatedSummary`:
- `plain_language_summary`: ≤ 3 sentences, no URLs, non-empty
- `advocacy_relevance`: ≤ 2 sentences, no URLs, non-empty
- `suggested_actions`: 1–3 items, ≤ 25 words each, no URLs
- `suggested_talking_points`: 1–3 items, ≤ 25 words each, no URLs
- `disclaimer`: must be exactly `"This summary is informational only and does not constitute legal advice."`

### Section classification
| Condition | Section |
|-----------|---------|
| `type=PRORULE` + `confidence=HIGH` + `comments_close_on >= today` | **A** — Action Required |
| `type=RULE` or `NOTICE` + `confidence=HIGH` | **B** — Watchdog Monitoring |
| `confidence=NEEDS_CONFIRMATION` (any type) | **C** — Potential Matches |
| `type=PRORULE` with expired comment window | **C** — Potential Matches |

### Static link rule (never break)
All email links are built from DB columns only. The LLM must never produce URLs. Validator strips them silently.
- Source: `https://www.federalregister.gov/d/{document_number}`
- Comment: `https://www.regulations.gov/commentOn?D={comment_url}` (or used as-is if already a full URL)

### Phase 3 callable interface (used by orchestrator.py)
```python
from phase_3.validator import validate_blob
result = validate_blob(doc_number, xml_blob)   # sync
# result.passed (bool), result.error_detail (str)

from phase_3.persistence import persist_validated_document
await persist_validated_document(doc_number)   # async, idempotent

from phase_3.digest_query import fetch_digest_rows
rows = await fetch_digest_rows(run_date)        # async

from phase_3.digest_builder import build_digest
package = build_digest(rows, run_date)          # sync — no await
# package.html_body, package.text_body, package.section_a/b/c_count, package.is_zero_result
```

### Step 4 remaining
`platform_handoff.py` — sends `DigestPackage` via Open Paws. The `# TODO Step 4` comment in `router.py` marks the exact integration point. Needs Open Paws API endpoint + key from project lead.

### Design rules (never break)
1. No ORM — raw SQL via `sqlalchemy.text()` only
2. No LLM calls anywhere in Phase 3
3. No imports from `phase_1` or `phase_2` — orchestrator is the only bridge
4. Idempotency everywhere — `persist_validated_document` is safe to call twice
5. Static links only — never interpolate LLM text into a URL
6. `DigestPackage` is a Pydantic model — required for FastAPI `response_model` serialization