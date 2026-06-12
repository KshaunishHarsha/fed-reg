# Federal Register Sentinel — CLAUDE.md

> Single source of truth for the entire project. Read this before touching any code.
> **Rule: never modify files outside your assigned phase without explicit user approval.**

---

## Project

Automated regulatory monitoring tool for the **Animal Legal Defense Fund (ALDF)**, integrated into their **Open Paws** platform. Replaces manual daily Federal Register review by attorneys and policy staff.

Built by a two-person team. Primary stakeholder/reviewer: **Chris** (ALDF). Feedback from Chris drives the next iteration of work.

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
curl -X POST "http://localhost:8000/run?date=2026-06-01"

# Phase 1 standalone — dry-run (real FR API, no AI or DB writes)
cd phase_1 && python pipeline.py --dry-run --date 2026-06-01

# Full Phase 1 standalone run
cd phase_1 && python pipeline.py --date 2026-06-01

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
├── frontend/               # Legacy demo UI (fallback only — Astro is primary)
│   └── index.html          # Self-contained single-page demo — no build step
│
├── sentinel-frontend/      # Astro static site — primary demo UI, deployed to Vercel
│   ├── src/pages/index.astro   # Main page: login gate + pipeline trigger + subscriber panel
│   ├── src/layouts/Layout.astro
│   ├── public/             # ALDF + OpenPaws logos
│   └── astro.config.mjs
│
├── phase_1/                # Ingestion + filtering
│   ├── config.py           # All constants: agency slugs, keywords, thresholds, model
│   ├── keywords.yaml       # Keyword source of truth — anchor, anchor_wb, context, noise_title
│   ├── models.py           # RawDocument → FilteredDocument → ConfirmedDocument
│   ├── ingestion.py        # Layer 1: FR API fetch + dedup
│   ├── keyword_filter.py   # Layer 2 + 2a: noise filter, keyword scoring, PDF scan
│   ├── ai_verification.py  # Layer 3: GPT-4o-mini via OpenRouter + instructor
│   ├── database.py         # psycopg2 helpers (synchronous) — Railway Postgres via DATABASE_URL
│   ├── pipeline.py         # CLI entry point: --date, --dry-run
│   ├── schema.sql          # Authoritative full-system DB schema (run once in Railway SQL)
│   ├── requirements.txt
│   └── tests/              # 43 tests
│
├── phase_2/                # LLM summarization
│   ├── models.py           # DocumentRecord (DB read), DocumentSummary (LLM output + validators)
│   ├── xml_builder.py      # Deterministic XML serialization — no LLM
│   ├── boilerplate_pruner.py # Tier 2: fetch body_html_url, strip noise sections
│   ├── tier_router.py      # Route by page_length → Tier 1 / 2 / 3
│   ├── summarizer.py       # GPT-4o-mini via OpenRouter, temp=0, instructor self-correct
│   ├── comment_drafter.py  # "Draft a Comment" — on-demand public comment letter from stored talking points
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
    ├── mailing_list.py     # add_subscriber(), get_active_recipients() — async, DB-backed
    ├── digest_query.py     # fetch_digest_rows(run_date) — async
    ├── digest_builder.py   # build_digest(rows, run_date) → DigestPackage — sync
    ├── mail_test.py        # SMTP send; falls back to test_recipients.yaml when DB list is empty
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
| `DATABASE_URL` | Phase 1 `database.py` (psycopg2), Phase 2 `database.py`, Phase 3 `db.py` | Railway Postgres. Phase 1 strips `+asyncpg` prefix internally; all other phases use `postgresql+asyncpg://...` |
| `SMTP_HOST` | Phase 3 `mail_test.py` | e.g. `smtp.gmail.com` |
| `SMTP_PORT` | Phase 3 `mail_test.py` | e.g. `465` (SSL) |
| `SMTP_USER` | Phase 3 `mail_test.py` | Gmail address / SMTP login |
| `SMTP_PASSWORD` | Phase 3 `mail_test.py` | Gmail App Password (16 chars) |
| `SMTP_FROM` | Phase 3 `mail_test.py` | Sender display string |
| `ALLOWED_ORIGINS` | `main.py` CORS middleware | Comma-separated allowed origins. Set to Vercel URL in production. |
| `PUBLIC_PASSWORD` | `sentinel-frontend` (Astro build-time) | Demo login password. Set in Vercel env vars. Empty = gate disabled. |

How each phase loads `.env`:
- Phase 1 + 2: `load_dotenv(Path(__file__).parent.parent / ".env")`
- Root files (`main.py`, `orchestrator.py`): `load_dotenv(Path(__file__).parent / ".env")`

No inter-phase HTTP URLs needed. All phases run in the same process via `orchestrator.py`.

> Phase 3's `router.py` also reads `PHASE1_RUN_URL`, `PHASE2_RUN_URL`, `PHASE2_CORRECTION_URL` for its
> own legacy `/phase3/run` endpoint. These are not needed when running through `POST /run`.

---

## Database

Authoritative schema: **`phase_1/schema.sql`** — run once in Railway SQL Editor.

| Table | Writer | Purpose |
|-------|--------|---------|
| `documents` | Phase 1 creates; Phase 2 + 3 update `pipeline_state` | One row per FR document. PK: `document_number`. |
| `summaries` | Phase 2 | `xml_summary_blob`, `summarization_tier`, `summarization_status`, `correction_attempts`. FK → `documents`. |
| `filter_audit` | Phase 1 | Every Layer 3 AI decision logged here. No FK to documents (logs dropped docs too). |
| `mailing_list` | `phase_3/mailing_list.py` via endpoints | Subscriber emails + preferences for the daily digest. PK: `id`. `email` is UNIQUE. `enabled` flag. 7 `pref_*` category columns + 7 `pref_agency_*` agency columns, all `DEFAULT true`. |

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
GET /  (main.py)
    └── Serves sentinel-frontend/dist/ (Astro build) — falls back to frontend/index.html if dist absent

POST /demo/run  (main.py)          ← demo only; not in production
    ├── phase_3.mailing_list.add_subscriber(email)   [upsert to DB]
    └── BackgroundTask: orchestrator.run_full_pipeline()

POST /run  (main.py)               ← production cron entry point
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
                    → phase_3.mailing_list.get_active_recipients_with_prefs() [async, DB-backed]
                    → per subscriber: filter sections by allowed_categories AND allowed_agencies (AND logic)
                    → phase_3.digest_builder.build_digest(filtered, run_date, _pre_classified=True)
                    → phase_3.mail_test.send_test_digest(recipients=[email])  [SMTP, per subscriber]
                    → if DEMO=true AND all sends succeeded: DELETE FROM documents (reset for re-run)
                    → TODO Step 4: platform_handoff.send_digest(package)
```

---

## All Endpoints (port 8000)

| Endpoint | Source | Purpose |
|----------|--------|---------|
| `GET /` | `main.py` | Demo frontend (Astro `sentinel-frontend/dist/`; legacy `frontend/index.html` as fallback) |
| `POST /demo/run` | `main.py` | **Demo only.** Subscribe email + trigger pipeline as background task. |
| `POST /run?date=YYYY-MM-DD` | `main.py` → `orchestrator.py` | **Primary cron entry point.** Full Phase 1→2→3 in-process. |
| `GET /health` | `main.py` | Liveness check |
| `POST /phase2/run` | `phase_2/api.py` | Phase 2 standalone — no Phase 3 callback |
| `POST /phase2/correct` | `phase_2/api.py` | Correction hook — reruns LLM for one doc |
| `GET /phase2/draft-comment?document_number=...` | `phase_2/api.py` | "Draft a Comment" — generates a public comment letter from stored talking points |
| `POST /phase3/run` | `phase_3/router.py` | Legacy cron path (calls Phase 1+2 via HTTP env vars — superseded by `POST /run`) |
| `POST /phase3/ingest` | `phase_3/router.py` | Per-document validate + persist |
| `GET /phase3/status/{doc_num}` | `phase_3/router.py` | Read `documents.pipeline_state` |
| `POST /phase3/digest/test` | `phase_3/router.py` | Dev — compile digest from existing DB rows |
| `POST /phase3/mail/test` | `phase_3/router.py` | Dev — compile + send via SMTP to `test_recipients.yaml` |
| `POST /phase3/validate/test` | `phase_3/router.py` | Dev — validate a raw XML blob in isolation |
| `GET /phase3/subscribers` | `phase_3/router.py` | Demo frontend — list active subscribers `[{email, created_at, preferences}]` |
| `POST /phase3/subscribe` | `phase_3/router.py` | Demo frontend — add/re-enable email on mailing list; accepts optional `preferences` dict |
| `PATCH /phase3/preferences` | `phase_3/router.py` | Update category and/or agency preferences for an existing subscriber |
| `DELETE /phase3/unsubscribe` | `phase_3/router.py` | Demo frontend — soft-delete email (sets `enabled=false`) |

---

## Build Status

| Component | Status | Notes |
|-----------|--------|-------|
| `main.py` + `orchestrator.py` | ✅ Complete | Unified app, direct in-process phase calls |
| **Frontend** — Astro Demo UI | ✅ Complete | `sentinel-frontend/` deployed to Vercel; password gate via `PUBLIC_PASSWORD`; `POST /demo/run` handles subscribe + pipeline trigger |
| **Mailing list** — DB-backed subscribers | ✅ Complete | `mailing_list` table (Railway); `phase_3/mailing_list.py`; orchestrator reads from DB, falls back to YAML |
| **Phase 1** — Ingestion + Filtering | ✅ Complete | 43 tests passing; migrated from supabase-py to psycopg2 (Railway Postgres) |
| **Phase 2** — LLM Summarization | ✅ Complete | 69 tests passing |
| **Phase 3** — Validation, Digest, Email | ✅ Steps 1–3 complete | Step 4 (`platform_handoff.py`) not yet implemented |
| **Deployment** | ✅ Complete | Backend on Railway (port 8000); Astro frontend on Vercel; `ALLOWED_ORIGINS` controls CORS |

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

### Relevancy grade (hybrid: keyword + AI)
`VerificationResult.relevancy` is `HIGH` / `MEDIUM` / `LOW`. Pipeline auto-maps anchor-keyword hits (keyword tier `HIGH`) to `HIGH` without trusting the AI; context-only docs (keyword tier `NEEDS_CONFIRMATION`) take the AI's `MEDIUM` / `LOW` grade. The result is written to `documents.confidence` (column repurposed from the old keyword tier). The keyword tier itself stays internal to Phase 1 and is still logged to `filter_audit.layer2_confidence`. Phase 3 renders this as a relevancy badge (see Phase 3 section classification).

### context_block stored in DB
Phase 2 Tier 3 (>50 page docs) reuses the `context_block` Phase 1 assembled. Avoids re-downloading PDFs.

### Phase 1 DB uses psycopg2 (not SQLAlchemy)
Phase 1 is synchronous. `database.py` connects via `psycopg2` using `DATABASE_URL` (strips `+asyncpg` prefix). All functions open a fresh connection, use a `RealDictCursor`, and close in a `try/finally`. `save_confirmed_document()` uses `INSERT ... ON CONFLICT (document_number) DO NOTHING`. Never overwrites.

### Keyword config — YAML is the only source of truth
`keywords.yaml` has four global lists: `anchor_terms` (substring match), `anchor_terms_word_boundary` (regex `\b`), `context_terms`, `noise_title_keywords`. All terms are lowercased at load time in `config.py`. No DB table for keywords — YAML is it. Abbreviations (AWA, APHIS, NMFS, etc.) are in `anchor_terms_word_boundary` to avoid false positives (e.g., "award"). CITES excluded entirely since "cites" is a common verb.

### Agency-specific filtering
Added 2026-06-10. Each of the 7 target agencies has a different signal-to-noise profile, so `keywords.yaml` also has an `agency_filters` section keyed by FR agency slug. Each entry supports three optional fields:

- `extra_anchor_terms`: agency-scoped phrases that give HIGH confidence (unambiguous within this agency's domain but too noisy globally).
- `extra_context_terms`: agency-scoped terms scored +1 each, added to the global pool.
- `context_threshold_override`: replaces `CONTEXT_THRESHOLD` for docs from this agency.

| Agency | Threshold override | Rationale |
|--------|-------------------|-----------|
| APHIS | 1 (lower) | Almost exclusively animal-welfare relevant |
| FSIS | 1 (lower) | Tightly focused on humane slaughter |
| FWS | 1 (lower) | ESA listings, refuge rules — very high relevance |
| NOAA | none (uses global 2) | High relevance but benefits from fishery-specific extra terms |
| FDA | 3 (higher) | Mostly human food/drugs; animal docs are a small fraction |
| NIH | 3 (higher) | Mostly human health research |
| AMS | 3 (higher) | Market orders; low relevance unless touching livestock welfare |

**Multi-agency docs:** the most permissive threshold among matching agencies wins (false-negatives-are-worse policy).

**Implementation:** `RawDocument` now carries `agency_slugs: List[str]` (populated from the FR API `agencies` array in `ingestion.py`). `config.py` loads agency filters into `AGENCY_FILTERS: dict[str, AgencyFilter]` (`AgencyFilter` is a dataclass). `keyword_filter._score_keywords()` looks up each doc's slugs, checks agency-specific anchor terms before globals, merges extra context terms into scoring, and picks the most permissive threshold.

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

### Draft a Comment (`comment_drafter.py`)
On-demand public comment letter for a proposed rule, triggered by a button in the digest email (Section A docs). Endpoint: `GET /phase2/draft-comment?document_number=...`.

- **Lives in Phase 2, not Phase 3.** Phase 3 forbids LLM calls (design rule #2), so the LLM drafting endpoint is `/phase2/draft-comment`, not `/phase3/`. The frontend calls Phase 2 directly.
- **Reuses, never re-reads.** It does NOT re-fetch the source PDF. It pulls the `advocacy_relevance` + `suggested_talking_points` already stored in `summaries.xml_summary_blob` from the morning run, so the model only writes prose. Fast (~few seconds) and cheap.
- One GPT-4o-mini call via OpenRouter, `temperature=0`, no `instructor` (freeform text output, not a Pydantic model). The blocking call runs in `asyncio.to_thread` so it never blocks the event loop.
- Inputs (title, agencies, talking points) are wrapped in `<document_payload>` and URL-stripped, same prompt-injection convention as `summarizer.py`. The letter uses a literal `[Your Name/Organization]` placeholder.
- Returns `{document_number, title, agency_names, comments_close_on, source_url, regulations_gov_url, draft_comment}`. `regulations_gov_url` is built from `documents.comment_url` (docket ID → `commentOn?D=...`, or used as-is if already a URL).
- Errors raise `DraftCommentError` with an HTTP-style `.status` (404 doc/summary missing, 502 empty model output), surfaced by the endpoint as `HTTPException`.

---

## Phase 3 — Decisions and Quirks

### Validation rules (what Phase 2's XML must satisfy)
From `phase_3/models.py` — `ValidatedSummary`:
- `plain_language_summary`: ≤ 3 sentences, no URLs, non-empty
- `advocacy_relevance`: ≤ 2 sentences, no URLs, non-empty
- `suggested_actions`: 1–3 items, ≤ 25 words each, no URLs
- `suggested_talking_points`: 1–3 items, ≤ 25 words each, no URLs
- `disclaimer`: must be exactly `"This summary is informational only and does not constitute legal advice."`

### Section classification + relevancy (two independent axes)
**Section (action axis)** — driven only by `type` + comment window:
| Condition | Section |
|-----------|---------|
| `type=PRORULE` + `comments_close_on >= today` | **A** — Action Required |
| everything else (RULE, NOTICE, expired PRORULE, other types) | **B** — Regulatory Tracking |

Section C was removed (2026-06-10). It conflated low confidence with stale-but-relevant docs; both now live in A/B with a relevancy badge instead. The C plumbing (`_section_c`, `section_c_count`, template block) is retained but always empty, so the orchestrator needs no change.

**Relevancy (confidence axis)** — the `documents.confidence` column, repurposed to hold `HIGH` / `MEDIUM` / `LOW`:
- `HIGH` = strong keyword anchor match (Phase 1 auto-maps anchor hits).
- `MEDIUM` / `LOW` = AI-graded in `verify_document()` for context-only docs.
- Rendered as a per-card badge and used to sort entries within each section (HIGH first).
- `digest_builder._normalize_relevancy()` maps legacy `NEEDS_CONFIRMATION` → `LOW`, unknown/missing → `MEDIUM`.
- Migration for an existing Railway DB: run `phase_1/migration_relevancy.sql` (converts data + swaps the CHECK constraint).

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

from phase_3.mailing_list import (
    add_subscriber,
    get_active_recipients,
    get_active_recipients_with_prefs,
    get_active_subscribers,
    update_preferences,
    disable_subscriber,
)
await add_subscriber(email, preferences={"pref_wildlife": True, "pref_agency_fda": False, ...})  # upsert, prefs optional
recipients = await get_active_recipients()                # List[str] — for zero-result path
subs = await get_active_recipients_with_prefs()          # List[{email, allowed_categories: set[str], allowed_agencies: set[str]}]
await update_preferences(email, {"pref_trade": False, "pref_agency_nih": False})  # update subset of prefs (category and/or agency)
subs = await get_active_subscribers()                    # List[{email, created_at, preferences}] for UI
await disable_subscriber(email)                          # sets enabled=false (soft delete)

# build_digest now supports pre-classified fast-path for per-subscriber re-rendering:
package = build_digest([], run_date, _pre_classified=True, _section_a=fa, _section_b=fb, _section_c=fc)
# package._section_a/b/c (PrivateAttr) hold the raw DigestEntry lists for orchestrator filtering
```

### Mailing list — design notes
- `mailing_list` table is the single source of truth for subscriber addresses. `test_recipients.yaml` is a dev-only fallback used only when the DB list is empty.
- `add_subscriber` accepts an optional `preferences` dict `{pref_col: bool}` for any mix of category (`pref_*`) and agency (`pref_agency_*`) columns. Missing keys default to `True`. Uses `ON CONFLICT (email) DO UPDATE` — idempotent.
- `get_active_recipients` returns `[]` (not an error) when the table is empty — orchestrator skips email and DEMO cleanup.
- `get_active_recipients_with_prefs` returns `[{email, allowed_categories: set[str], allowed_agencies: set[str]}]` — used by orchestrator to filter each subscriber's digest with AND logic.
- `get_active_subscribers` returns full rows with `created_at` and `preferences` dict (all 14 columns) — used by the Astro frontend subscriber panel.
- `update_preferences(email, prefs_dict)` accepts any mix of category and agency pref keys, updates only the supplied columns — partial update safe.
- `disable_subscriber` soft-deletes: row stays in table, `enabled=false`. Re-subscribing via `add_subscriber` re-enables it.

### DEMO mode cleanup — invariants
- `DEMO=true` in `.env` enables post-send cleanup.
- Cleanup runs inside the `send_test_digest()` success path — **never before the email is delivered**.
- Zero-result (circuit-breaker) digests still trigger cleanup because `send_test_digest` renders the zero-result template and delivers it normally.
- If there are no active subscribers, no email is sent and no cleanup runs — the documents stay in the DB.
- Cleanup uses `DELETE FROM documents;` via Phase 3's SQLAlchemy session. `summaries` is cascade-deleted. `filter_audit` and `mailing_list` are untouched.

### Step 4 remaining
`platform_handoff.py` — sends `DigestPackage` via Open Paws. The `# TODO Step 4` comment in `router.py` marks the exact integration point. Needs Open Paws API endpoint + key from project lead.

### Design rules (never break)
1. No ORM — raw SQL via `sqlalchemy.text()` only
2. No LLM calls anywhere in Phase 3
3. No imports from `phase_1` or `phase_2` — orchestrator is the only bridge
4. Idempotency everywhere — `persist_validated_document` is safe to call twice
5. Static links only — never interpolate LLM text into a URL
6. `DigestPackage` is a Pydantic model — required for FastAPI `response_model` serialization

---

## Subscriber Preferences

Category preferences added 2026-06-10. Agency preferences added 2026-06-10.

### DB schema (mailing_list)
Fourteen boolean columns, all `DEFAULT true`:
```
-- Category (7)
pref_welfare, pref_wildlife, pref_agriculture, pref_agricultural_subsidies,
pref_research_animals, pref_marine, pref_trade

-- Agency (7)
pref_agency_ams, pref_agency_aphis, pref_agency_fsis, pref_agency_fda,
pref_agency_noaa, pref_agency_fws, pref_agency_nih
```
New `schema.sql` includes all 14 columns. Existing Railway deployments need migration (run `migrate_add_preferences.py`, gitignored).

### Category codes → display labels
| DB / Phase 2 code | Email sub-heading & UI label |
|---|---|
| `welfare` | Companion & Gen. Welfare |
| `wildlife` | Wild Animals & Habitat |
| `agriculture` | Livestock Regulations |
| `agricultural_subsidies` | Farm Subsidies & Loans |
| `research_animals` | Lab & Research Animals |
| `marine` | Marine & Ocean Life |
| `trade` | Animal Trade & Export |

Labels are defined in `CATEGORY_LABELS` dict in `phase_3/digest_builder.py`.

### Agency preference columns → canonical names
| DB column | Canonical name (matched against DigestEntry.agency_names) |
|---|---|
| `pref_agency_ams` | Agricultural Marketing Service |
| `pref_agency_aphis` | Animal and Plant Health Inspection Service |
| `pref_agency_fsis` | Food Safety and Inspection Service |
| `pref_agency_fda` | Food and Drug Administration |
| `pref_agency_noaa` | National Oceanic and Atmospheric Administration |
| `pref_agency_fws` | Fish and Wildlife Service |
| `pref_agency_nih` | National Institutes of Health |

Defined in `AGENCY_PREF_COLUMNS` in `phase_3/mailing_list.py`. Matching uses substring search against `DigestEntry.agency_names` (handles FR API name variations).

### Per-subscriber email flow
1. Orchestrator calls `get_active_recipients_with_prefs()` → list of `{email, allowed_categories, allowed_agencies}`.
2. For each subscriber: filter `package._section_a/b/c` entries using AND logic — a document appears only if its `regulation_category` is in `allowed_categories` AND at least one of its `agency_names` matches a name in `allowed_agencies`.
3. If no documents match → skip (no blank email sent).
4. Call `build_digest(..., _pre_classified=True, _section_a=fa, _section_b=fb, _section_c=fc)` to render a personalized HTML/text body.
5. Send via `send_test_digest(recipients=[email])` — one SMTP call per subscriber.

### Phase 2 prompt
`phase_2/summarizer.py` lists `agricultural_subsidies` as a valid `regulation_category` with explicit instructions (USDA loans, CAFO financing, livestock indemnity payments).

### Frontend (Astro)
- Subscribe form shows two 2-column checkbox grids: one for categories, one for agencies. All ticked by default.
- JS reads all checkboxes by name and POSTs `{email, preferences: {pref_*: bool, pref_agency_*: bool}}` to `POST /phase3/subscribe`.
- Subscriber list renders category tags (grey) and agency tags (teal) under each row.
- `PATCH /phase3/preferences` endpoint accepts any mix of `pref_*` and `pref_agency_*` keys.

---

## Demo Mode

To enable a repeatable demo environment, set `DEMO=true` in `.env`.

### Demo Cleanup (`DELETE FROM documents;`)
When `DEMO=true`, the `orchestrator.py` runs a special cleanup routine at the very end of `run_full_pipeline` (after the digest email is sent). It executes `DELETE FROM documents;` in the Phase 3 database session. 
- Because `summaries` has an `ON DELETE CASCADE` mapped to `documents`, this wipes all saved state for the run.
- This allows you to repeatedly test the same date (e.g., via the frontend date picker) without Phase 1 cache preventing re-ingestion, and without cluttering the database.

### "0 Docs Found" / Zero-Result Emails
If you select a random date, you will often see **"0 confirmed relevant documents"** and receive an empty, circuit-breaker email. This is **expected and correct behavior**:
- Phase 1 Layer 2 (Keyword Filter) might find documents (e.g., a "Fish and Wildlife Service" administrative meeting).
- Phase 1 Layer 3 (AI Verification) will accurately identify that the document is *not* relevant to animal law advocacy and will reject it (`is_relevant=False`).
- If 0 documents pass, Phase 2 is skipped, but Phase 3 compiles and sends the "zero result" fallback email template to prove the system ran successfully.
- To guarantee documents in a demo, you must select a date known to have published an animal-relevant proposed or final rule.