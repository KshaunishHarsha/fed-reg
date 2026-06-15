# Federal Register Sentinel

Automated daily regulatory monitoring system for the **Animal Legal Defense Fund (ALDF)**, built for integration into the **Open Paws** platform. Replaces manual daily review of the Federal Register by attorneys and policy staff.

Every morning, a cron job triggers a full pipeline run that:
1. Pulls that day's Federal Register publications from 7 target agencies
2. Filters to animal-relevant documents through a 4-layer keyword + AI pipeline
3. Generates plain-language advocacy summaries via LLM
4. Validates, classifies, and emails a personalized daily digest to each subscriber

---

## Architecture

One process. One port (8000). All inter-phase calls are direct Python function calls — no HTTP between phases.

```
POST /run  (cron entry point)
    └── orchestrator.run_full_pipeline(target_date)
            ├── Phase 1: Ingestion + Filtering
            ├── Phase 2: LLM Summarization  (per document, with Phase 3 validation callback)
            └── Phase 3: Digest compilation + per-subscriber email delivery
```

The backend is a single FastAPI app (`main.py`) running on Railway at port 8000. The orchestrator (`orchestrator.py`) sequences all three phases in-process.

---

## Repository Structure

```
fed-reg/
├── main.py                 # Unified FastAPI app — single entry point, port 8000
├── orchestrator.py         # Phase 1 → 2 → 3 sequential orchestration
├── phase_1/                # Ingestion + filtering
│   ├── config.py           # Agency slugs, keywords, thresholds, model
│   ├── keywords.yaml       # Keyword source of truth
│   ├── models.py           # RawDocument → FilteredDocument → ConfirmedDocument
│   ├── ingestion.py        # Layer 1: FR API fetch + dedup
│   ├── keyword_filter.py   # Layer 2 + 2a: noise filter, keyword scoring, PDF scan
│   ├── ai_verification.py  # Layer 3: GPT-4o-mini via OpenRouter
│   ├── database.py         # psycopg2 helpers (synchronous)
│   ├── schema.sql          # Authoritative full-system DB schema
│   └── tests/              # 43 tests
├── phase_2/                # LLM summarization
│   ├── models.py           # DocumentRecord, DocumentSummary
│   ├── tier_router.py      # Routes by page_length → Tier 1/2/3
│   ├── boilerplate_pruner.py # Tier 2: fetch + strip document body
│   ├── summarizer.py       # GPT-4o-mini via OpenRouter, temp=0
│   ├── xml_builder.py      # Deterministic XML serialization
│   ├── comment_drafter.py  # Draft a Comment — on-demand comment letter generation
│   ├── database.py         # Async SQLAlchemy raw SQL
│   ├── pipeline.py         # Phase 2 orchestrator
│   ├── api.py              # APIRouter included in main.py
│   └── tests/              # 69 tests
└── phase_3/                # Validation, digest compilation, email delivery
    ├── validator.py        # Validates Phase 2 XML blobs
    ├── xml_parser.py       # ElementTree parse of xml_summary_blob
    ├── persistence.py      # Idempotent pipeline_state promotion
    ├── digest_query.py     # Fetches SUMMARY_GENERATED docs for a date
    ├── digest_builder.py   # Section A/B classification + Jinja2 rendering
    ├── mailing_list.py     # Subscriber management — async, DB-backed
    ├── mail_test.py        # SMTP delivery
    ├── router.py           # APIRouter — all Phase 3 endpoints
    └── templates/          # digest_email.html/txt, zero_result.html/txt
```

---

## Environment Variables

All secrets live in `.env` at the repo root.

| Variable | Used By | Purpose |
|----------|---------|---------|
| `OPENROUTER_API_KEY` | Phase 1, Phase 2 | OpenRouter key → `openai/gpt-4o-mini` |
| `DATABASE_URL` | All phases | Railway Postgres (`postgresql+asyncpg://...`). Phase 1 strips `+asyncpg` internally. |
| `SMTP_HOST` | Phase 3 | e.g. `smtp.gmail.com` |
| `SMTP_PORT` | Phase 3 | e.g. `465` (SSL) |
| `SMTP_USER` | Phase 3 | Gmail address / SMTP login |
| `SMTP_PASSWORD` | Phase 3 | Gmail App Password (16 chars) |
| `SMTP_FROM` | Phase 3 | Sender display string |
| `FRONTEND_URL` | Phase 3 | URL of the frontend. Used to build "Draft a Comment" deep-links in the digest email. |
| `ALLOWED_ORIGINS` | `main.py` | Comma-separated CORS origins. |

---

## Database

Authoritative schema: `phase_1/schema.sql` — run once in the Railway SQL editor.

| Table | Writer | Purpose |
|-------|--------|---------|
| `documents` | Phase 1 (Phase 2 + 3 update `pipeline_state`) | One row per FR document. PK: `document_number`. |
| `summaries` | Phase 2 | `xml_summary_blob`, `summarization_tier`, `summarization_status`, `correction_attempts`. FK → `documents` (CASCADE). |
| `filter_audit` | Phase 1 | Every Layer 3 AI decision, including dropped documents. No FK to `documents`. |
| `mailing_list` | Phase 3 `mailing_list.py` | Subscriber emails + 14 preference columns. `email` is UNIQUE. |

### `pipeline_state` lifecycle

```
INGESTED               ← Phase 1 writes on document creation
    ↓
SUMMARY_GENERATED      ← Phase 2 writes on successful summarization
SUMMARIZATION_FAILED   ← Phase 2 writes on permanent LLM failure (>2 retries)
    ↓
DIGEST_SENT            ← Phase 3 writes after validation + digest inclusion
```

---

## Phase 1 — Ingestion and Filtering

Phase 1 runs synchronously in a `ThreadPoolExecutor` (it is the only synchronous phase). It pulls FR publications for the target date and passes each document through four layers.

### Target Agencies

| Agency Slug | Full Name |
|-------------|-----------|
| `aphis` | Animal and Plant Health Inspection Service |
| `fsis` | Food Safety and Inspection Service |
| `fws` | Fish and Wildlife Service |
| `noaa` | National Oceanic and Atmospheric Administration |
| `fda` | Food and Drug Administration |
| `nih` | National Institutes of Health |
| `ams` | Agricultural Marketing Service |

### Layer 1 — FR API Fetch

`ingestion.py` pulls from two Federal Register endpoints for each target date:

- **Published documents** (`/documents.json`): server-side filtered by agency slug and document type (`RULE`, `PRORULE`, `NOTICE`). Paginated — follows `next_page_url` until exhausted.
- **Public inspection** (`/public-inspection/{date}.json`): no server-side filtering available; agency slug and type are filtered client-side. Returns 404 on weekends and holidays — handled gracefully.

Known FR API quirks:
- Use `type` not `document_type` — the latter returns a 400.
- Public inspection docs may lack `abstract`, `page_length`, `comments_close_on`.
- `PRESDOCU` is excluded from target document types by design.

Deduplication is by `document_number` — the FR's globally unique identifier and the primary key across all tables.

### Layer 2 — Keyword Scoring

`keyword_filter.py` scores each document against four global keyword lists defined in `keywords.yaml`:

| List | Match type | Effect |
|------|------------|--------|
| `anchor_terms` | Substring | Instant HIGH confidence — bypasses context threshold |
| `anchor_terms_word_boundary` | Regex `\b` | Same as anchor but prevents substring false positives (e.g., "AWA" matching "award") |
| `context_terms` | Substring | +1 per match; must reach threshold to pass |
| `noise_title_keywords` | Title match | Immediate drop regardless of other scores |

**Agency-specific overrides** — each agency has a different signal-to-noise ratio, so `keywords.yaml` supports per-agency configuration:

| Agency | Context threshold | Rationale |
|--------|-------------------|-----------|
| APHIS | 1 (lower) | Almost exclusively animal-welfare relevant |
| FSIS | 1 (lower) | Tightly focused on humane slaughter |
| FWS | 1 (lower) | ESA listings, refuge rules |
| NOAA | 2 (global default) | High relevance but benefits from fishery-specific terms |
| FDA | 3 (higher) | Mostly human food/drugs |
| NIH | 3 (higher) | Mostly human health research |
| AMS | 3 (higher) | Market orders; low relevance unless touching livestock welfare |

For multi-agency documents, the most permissive threshold among matching agencies wins (false negatives are worse than false positives).

### Layer 2a — PDF Scan

Runs only when a document has no `abstract` AND passed keyword scoring. Fetches the PDF, extracts text from the first few pages, and re-scores against the keyword lists.

### Layer 3 — AI Verification

`ai_verification.py` sends documents that passed at least one keyword check to GPT-4o-mini via OpenRouter. The model returns:

- `is_relevant` (bool) — final gate
- `relevancy` (`HIGH` / `MEDIUM` / `LOW`) — confidence grade
- `regulation_category` — one of 7 animal-law topic codes

**Hybrid relevancy grading:** anchor-keyword hits are auto-promoted to `HIGH` without trusting the AI grade. Context-only documents (those that only passed context scoring) take the AI's `MEDIUM` or `LOW` grade. This prevents the AI from downgrading documents with unambiguous anchor matches.

The relevancy grade is stored in `documents.confidence` and used by Phase 3 for card sorting and badge rendering.

**Idempotency:** `is_already_processed()` checks the DB before every AI call. Safe to rerun after crashes.

**Audit logging:** every Layer 3 decision (including drops) is written to `filter_audit`. No FK to `documents` — dropped documents are never in that table.

---

## Phase 2 — LLM Summarization

Phase 2 reads all `INGESTED` documents for the target date from the DB and summarizes each one. It runs asynchronously and processes documents sequentially, invoking the Phase 3 validation callback after each one.

### Tier Routing

Documents are routed to one of three summarization tiers based on `page_length`:

| Tier | Condition | Text source |
|------|-----------|-------------|
| 1 | `page_length < 15` or `None` | `abstract` → fallback: `title` |
| 2 | `15 ≤ page_length ≤ 50` | `boilerplate_pruner.prune()` → fallback: `abstract` → `title` |
| 3 | `page_length > 50` | `context_block` from DB (assembled by Phase 1) — never re-fetches PDF |

`boilerplate_pruner.py` (Tier 2) makes one additional FR API call per document to fetch `body_html_url`, then strips noise sections (preamble boilerplate, regulatory text, signature blocks) before passing the body to the LLM.

Tier 3 reuses the `context_block` Phase 1 stored in the DB during Layer 2a, avoiding repeated PDF downloads for large documents.

### LLM Output Schema

Each document produces a structured XML blob (`xml_summary_blob`) stored in `summaries`:

```xml
<regulatory_document_summary>
  <plain_language_summary>...</plain_language_summary>   <!-- ≤ 3 sentences -->
  <advocacy_relevance>...</advocacy_relevance>           <!-- ≤ 2 sentences -->
  <suggested_actions>
    <action>...</action>                                 <!-- 1–3 items, ≤ 25 words each -->
  </suggested_actions>
  <suggested_talking_points>
    <point>...</point>                                   <!-- 1–3 items, ≤ 25 words each -->
  </suggested_talking_points>
  <regulation_category>wildlife</regulation_category>   <!-- one of 7 topic codes -->
  <disclaimer>This summary is informational only...</disclaimer>
</regulatory_document_summary>
```

All LLM calls use `temperature=0` for deterministic, auditable output. Document content is wrapped in `<document_payload>` tags and URLs are stripped before reaching the model (prompt injection prevention). The `disclaimer` field is always overwritten with a hardcoded constant regardless of LLM output.

### Self-Correction Loops

Two independent correction mechanisms run in sequence:

1. **instructor self-correction** (max 2 retries): catches Pydantic validation failures (word count, list length, etc.) within a single `summarize()` call. Handled entirely within Phase 2.

2. **Phase 3 correction** (max 2 retries): if Phase 3's XML validator rejects a blob after delivery, the orchestrator calls `handle_correction(doc_num, error_detail)`. Phase 2 re-runs the LLM with the error detail as a correction note and increments `correction_attempts` in the DB. If `correction_attempts > 2`, the document is marked `summarization_status = 'failed'` and excluded from the digest.

### Draft a Comment

`GET /phase2/draft-comment?document_number=...`

On-demand generation of a formal public comment letter, triggered from a button in the digest email for Section A documents. The endpoint reuses the `advocacy_relevance` and `suggested_talking_points` already stored in `summaries.xml_summary_blob` — it never re-fetches the source document. One GPT-4o-mini call produces a 3–4 paragraph letter with a `[Your Name/Organization]` placeholder. Returns `{ document_number, title, agency_names, comments_close_on, source_url, regulations_gov_url, draft_comment }`.

---

## Phase 3 — Validation, Digest, and Email

Phase 3 has no LLM calls. It validates Phase 2 output, compiles the digest, and sends a personalized email to each active subscriber.

### XML Validation

`validator.py` checks every `xml_summary_blob` against the output contract before a document is included in the digest:

- `plain_language_summary`: ≤ 3 sentences, no URLs, non-empty
- `advocacy_relevance`: ≤ 2 sentences, no URLs, non-empty
- `suggested_actions`: 1–3 items, ≤ 25 words each, no URLs
- `suggested_talking_points`: 1–3 items, ≤ 25 words each, no URLs
- `disclaimer`: must match exactly `"This summary is informational only and does not constitute legal advice."`

On failure, the orchestrator triggers the Phase 2 correction loop (up to 2 retries). On permanent failure, the document is excluded from the digest.

### Section Classification

Documents are classified into two sections based solely on DB columns — never LLM output:

| Condition | Section |
|-----------|---------|
| `comments_close_on >= today` (any document type) | **A — Action Required** |
| No comment window, or comment window expired | **B — Regulatory Tracking** |

Section A contains all actionable documents where a public comment can still be filed. This includes PRORULE documents as well as NOTICEs that reopen comment periods (the FR API files these as `NOTICE` type, not `PRORULE`).

Within each section, documents are sorted by relevancy grade: `HIGH` first, then `MEDIUM`, then `LOW`.

### Relevancy Grades

The `documents.confidence` column holds `HIGH` / `MEDIUM` / `LOW`, set by Phase 1:

- `HIGH`: strong anchor keyword match — auto-promoted by Phase 1, not dependent on AI grade
- `MEDIUM` / `LOW`: AI-graded for context-only documents

Rendered as a colored badge on every digest card.

### Digest Email

The digest is compiled using Jinja2 templates (`digest_email.html` and `digest_email.txt`). Each Section A card includes:

- Document title, agency, publication date, relevancy badge, regulation category
- Plain-language summary and advocacy relevance (from LLM)
- Comment deadline strip with days remaining
- Suggested actions and talking points
- **View Notice** button → `federalregister.gov/d/{document_number}`
- **Submit Comment** button → `regulations.gov/commentOn?D={comment_url}` (if docket URL exists)
- **Draft a Comment** button → `{FRONTEND_URL}/draft?doc={document_number}` (if `FRONTEND_URL` is set)

Section B cards include View Notice and Submit Comment only (no comment drafting for tracking-only documents).

All links are built from DB columns. The LLM never produces URLs — the validator strips them silently if detected.

If no documents pass Phase 1 filtering for the day, Phase 3 sends a zero-result circuit-breaker email confirming the system ran successfully.

### Per-Subscriber Personalization

Each subscriber has 14 boolean preference columns in the `mailing_list` table:

**Category preferences (7):**

| DB column | Display label |
|-----------|---------------|
| `pref_welfare` | Companion & Gen. Welfare |
| `pref_wildlife` | Wild Animals & Habitat |
| `pref_agriculture` | Livestock Regulations |
| `pref_agricultural_subsidies` | Farm Subsidies & Loans |
| `pref_research_animals` | Lab & Research Animals |
| `pref_marine` | Marine & Ocean Life |
| `pref_trade` | Animal Trade & Export |

**Agency preferences (7):**

| DB column | Agency |
|-----------|--------|
| `pref_agency_ams` | Agricultural Marketing Service |
| `pref_agency_aphis` | Animal and Plant Health Inspection Service |
| `pref_agency_fsis` | Food Safety and Inspection Service |
| `pref_agency_fda` | Food and Drug Administration |
| `pref_agency_noaa` | National Oceanic and Atmospheric Administration |
| `pref_agency_fws` | Fish and Wildlife Service |
| `pref_agency_nih` | National Institutes of Health |

**Per-subscriber email flow:**

1. Fetch all active subscribers with their preference sets from the DB
2. For each subscriber, filter digest entries using AND logic: a document appears only if its `regulation_category` matches an allowed category AND at least one of its `agency_names` matches an allowed agency
3. If no documents match after filtering, skip that subscriber (no blank email sent)
4. Re-render the digest HTML/text with the filtered entry set
5. Send one SMTP email per subscriber

### Mailing List Management

Subscribers are managed via the `mailing_list` table. Key behaviors:
- `add_subscriber` is idempotent (`ON CONFLICT DO UPDATE`) — re-subscribing re-enables a soft-deleted row
- `disable_subscriber` soft-deletes: sets `enabled = false`, row stays in table
- All 14 preference columns default to `true` — new subscribers receive the full digest unless they opt out

---

## Running the Pipeline

```bash
# Install dependencies
pip install -r requirements.txt

# Start the server
python main.py

# Trigger a full pipeline run for today
curl -X POST http://localhost:8000/run

# Trigger for a specific date (backfill / testing)
curl -X POST "http://localhost:8000/run?date=2026-06-01"

# Phase 1 dry-run (real FR API, no AI calls, no DB writes)
cd phase_1 && python pipeline.py --dry-run --date 2026-06-01

# Run tests
cd phase_1 && python -m pytest tests/ -v   # 43 tests
cd phase_2 && python -m pytest tests/ -v   # 69 tests
```

---

## Key Endpoints

| Endpoint | Purpose |
|----------|---------|
| `POST /run?date=YYYY-MM-DD` | Primary cron entry point — full Phase 1→2→3 pipeline |
| `GET /health` | Liveness check |
| `GET /phase2/draft-comment?document_number=...` | On-demand comment letter generation |
| `POST /phase2/correct` | Reruns LLM for one document with a correction note |
| `GET /phase3/status/{doc_num}` | Read `documents.pipeline_state` |
| `POST /phase3/digest/test` | Dev — compile digest from existing DB rows |
| `POST /phase3/mail/test` | Dev — compile and send via SMTP |
| `POST /phase3/subscribe` | Add or re-enable a subscriber |
| `PATCH /phase3/preferences` | Update subscriber preferences |
| `DELETE /phase3/unsubscribe` | Soft-delete a subscriber |

---

## Deployment

- **Backend**: Railway, port 8000. Set all environment variables in Railway's variable panel.
- **Database**: Railway Postgres. Run `phase_1/schema.sql` once in the Railway SQL editor to initialize all tables.
- **Cron**: Configure a daily cron job to `POST /run` each morning after the Federal Register publishes (typically 8–9 AM ET).

---

## Frontend (Astro)

A static Astro site deployed to Vercel serves as the subscriber-facing frontend. It covers two features:

**Subscriber Preferences (`/`)**
- Subscribe form with two checkbox grids: one for the 7 category preferences, one for the 7 agency preferences. All ticked by default.
- POSTs `{ email, preferences: { pref_*: bool, pref_agency_*: bool } }` to `POST /phase3/subscribe`.
- Subscriber list displays active subscribers with their category (grey) and agency (teal) preference tags.
- Preference updates hit `PATCH /phase3/preferences`.
- Unsubscribe hits `DELETE /phase3/unsubscribe` (soft delete).

**Draft a Comment (`/draft?doc=...`)**
- Opened via the "Draft a Comment" button in Section A digest email cards.
- On load, fetches `GET /phase2/draft-comment?document_number=...` from the Railway backend.
- Displays the generated letter in an editable textarea with a copy-to-clipboard button and a "Submit on Regulations.gov" link.
- Handles 404 (document not found / no summary yet) and 502 (empty model output) errors gracefully.

The Astro site is configured via two build-time environment variables set in Vercel:
- `PUBLIC_API_URL` — Railway backend URL, used for all client-side API calls
- `PUBLIC_PASSWORD` — optional password gate for the site

---

## Design Principles

1. **False negatives are worse than false positives.** All keyword thresholds and AI prompts are tuned toward inclusion — it is better to surface a borderline document than to miss a relevant one.
2. **AI is a last resort.** GPT-4o-mini only sees documents that passed at least one keyword check. This controls cost and latency.
3. **No LLM calls in Phase 3.** All digest logic is deterministic.
4. **Static links only.** All outbound URLs in the digest are built from DB columns. LLM output never enters a URL.
5. **Idempotency everywhere.** The pipeline can be re-run safely after any crash without duplicating data.
6. **No ORM.** All DB access is raw SQL via `sqlalchemy.text()`.
