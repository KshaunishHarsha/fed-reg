# Phase 3 — Post-Processing and Email Delivery

## Purpose

Phase 3 is the final downstream stage of the Federal Register Sentinel pipeline. It does **not** interact with the Federal Register API or the LLM directly. Its sole responsibility is to receive the validated, summarized document envelopes produced by Phase 2, enforce a final quality gate, persist them to the database, and trigger the daily email digest build and delivery.

This phase is intentionally isolated — it reads from a shared database table and hands off to the existing Open Paws email infrastructure. No Phase 1 or Phase 2 code is imported here. This keeps the three contributors' work free from merge conflicts and makes each phase independently testable.

---

## Architecture: Where Phase 3 Lives

```
fed-reg/
├── phase_1/         ← teammate's work (ingestion + filtering)
├── phase_2/         ← teammate's work (summarization + LLM)
└── phase_3/         ← this folder (post-processing + delivery)
    ├── README.md                  ← this file
    ├── llm_output_contract.md     ← LLM output schema and field rules
    ├── validator.py               ← quality review and correction loop
    ├── persistence.py             ← database write + idempotency cache
    ├── digest_builder.py          ← HTML + plain-text email assembly
    ├── scheduler.py               ← APScheduler job (7:30 AM trigger)
    ├── platform_handoff.py        ← Open Paws delivery bundle + webhook
    └── templates/
        ├── digest_email.html      ← Jinja2 HTML email template
        └── digest_email.txt       ← Plain-text fallback template
```

> **FastAPI context:** This entire repository is a FastAPI backend. Phase 3 registers its own APIRouter (mounted at `/phase3/`) so its endpoints (e.g. manual trigger, status check, webhook receiver) are reachable without touching other phases' routes.

---

## Step-by-Step Operational Flow

### Step 1 — Automated Quality Review and Correction

**Trigger:** Phase 2 hands a completed `SummarizedDocument` Pydantic model to Phase 3's validation entry point.

**What happens:**

- Phase 3 runs every field in the envelope through a strict checklist (defined in detail in [llm_output_contract.md](llm_output_contract.md)):
  - All required LLM fields are present and non-empty
  - `plain_language_summary` ≤ 3 sentences
  - `advocacy_relevance` ≤ 2 sentences
  - `suggested_actions` and `suggested_talking_points`: 1–3 items each, ≤ 25 words per item
  - `disclaimer` is the exact hardcoded legal string
  - No URLs appear inside any LLM-generated field
  - Date formats in metadata fields match ISO standard (`YYYY-MM-DD`)

- **On failure:** Phase 3 raises a structured `ValidationError` containing the specific rule that failed. This error is caught by Phase 2's correction loop, which sends the failure reason back to the LLM as a system correction note. Phase 3 does not write anything to the database until the document passes.

- **On URL detection in LLM fields:** The URL is stripped silently and the event is written to the audit log. This is the one auto-corrected case that does not bounce back to Phase 2.

**Key files:** `validator.py`, `xml_parser.py`, `models.py`, `router.py`

#### Implementation Notes (Step 1)

**Schema alignment:**  
The `schemas.md` schema (owned by Phase 1) has no `validation_attempts` column, no `summarization_failed` pipeline state, and no separate validation table. Rather than adding columns to a schema we don't own, the self-correction loop is handled entirely as an **in-memory runtime concern** inside the FastAPI ingest endpoint (`router.py → _ingest_with_retry`). Documents that fail all retries simply stay at `pipeline_state = 'SUMMARY_GENERATED'` — they are never promoted to `DIGEST_SENT` and are therefore naturally excluded from the 7:30 AM digest query.

**Why not Instructor SDK here:**  
Instructor is a wrapper around the OpenAI client — it belongs in Phase 2, which owns the LLM call. Phase 3 never calls the LLM. Instead, Phase 3 produces a structured `error_detail` string (built from Pydantic's own error list) and POSTs it to Phase 2's correction endpoint. Phase 2's Instructor client then wraps that error string into the correction prompt. This keeps each phase's responsibilities clean.

**Retry limit:** `MAX_RETRIES = 2` (configurable constant in `router.py`) — matches the plan spec of 2 self-correction cycles. After 3 total attempts (initial + 2 retries), the endpoint returns HTTP 422 with the structured error detail. Phase 2 is responsible for its own failure logging.

**URL handling:** URLs found inside LLM-generated fields are **silently stripped** (not bounced back for retry), logged as a warning, and the cleaned text is re-validated. This is the one auto-corrected case.

---

### Step 2 — Database Storage and Automated Fail-Safe Routine

**Trigger:** Document passes Step 1 validation.

**What happens:**

- The document's `document_number` (e.g. `2026-09841`) is used as the unique primary key for the database row.
- Before writing, Phase 3 checks for an existing row with that key — if one exists, the write is skipped and the cached version is returned. This idempotency guard ensures the pipeline can safely re-run (e.g. after a crash or scheduler restart) without generating duplicate emails or paying to regenerate LLM summaries.
- If no row exists, Phase 3 writes the full `SummarizedDocument` envelope to the database, tagging it with:
  - `status: "approved"` — for documents that passed validation
  - `status: "flagged"` — for `confidence_tier: "confirmation_required"` borderline documents that still passed formatting checks (displayed in Section C of the digest)
  - `digest_date: publication_date` — used by the digest builder to query the correct day's entries

**Tech:** Supabase / PostgreSQL via an async SQLAlchemy session. Document number serves as the unique index.

**Key file:** `persistence.py`

---

### Step 3 — Digest Compilation and Layout Design

**Trigger:** APScheduler fires at **7:30 AM daily**, after Phase 1 and Phase 2 have had time to complete their full pipeline run.

**What happens:**

1. The digest builder queries the database for all rows where `digest_date = today`.

2. **Circuit Breaker — Zero-result day:**  
   If the query returns zero rows, the system does not go silent. A minimal digest is assembled and sent, stating clearly that no animal-relevant federal activity was identified for that date. This lets subscribers distinguish a quiet regulatory day from a system outage.

3. **If documents are found:**  
   The builder loops through the results and sorts them into three urgency sections:

   | Section | Label | Contents |
   |---|---|---|
   | **A** | High Priority | Documents with an open public comment period; `comment_deadline` is present and in the future. Closing dates are displayed prominently. |
   | **B** | Watchdog Monitoring | Finalized rules and informational notices; no active comment window. |
   | **C** | Potential Matches | Documents with `status: "flagged"` (borderline `confirmation_required` items). Displayed with a clear ⚠️ warning badge. |

4. The builder produces a **dual-layer email package**:
   - **HTML version:** Rich formatted template (Jinja2) with visual section dividers, urgency colors, and bold deadlines.
   - **Plain-text version:** Clean fallback for mobile mail clients and accessibility.

5. Every document entry in the digest includes:
   - Official title (from database metadata — not LLM)
   - Agency name (from database metadata)
   - `plain_language_summary`
   - `advocacy_relevance`
   - `suggested_actions` as a bullet list
   - `suggested_talking_points` as a bullet list
   - Direct link to the Federal Register source (from `federal_register_url` in database — **never from LLM text**)
   - Hardcoded disclaimer immediately below each entry

6. A master footer disclaimer is hardcoded into both the HTML and plain-text templates.

**Key files:** `digest_builder.py`, `templates/digest_email.html`, `templates/digest_email.txt`

---

### Step 4 — Secure Platform Handoff and Distribution

**Trigger:** Digest compilation completes successfully.

**What happens:**

- Phase 3 packages the HTML and plain-text bodies into a **single delivery bundle** (a structured request payload).
- This bundle is passed to the **existing Open Paws platform email system** via one secure HTTP request. Phase 3 does not manage subscriber lists, sender reputation, or SMTP credentials — all of that lives in Open Paws.
- The request instructs Open Paws to distribute the exact layout to the active subscriber segment for this notification type.

**Unsubscribe and opt-out handling:**

- Standard `List-Unsubscribe` headers are embedded in the outgoing mail headers by Open Paws, using subscriber-specific unsubscribe tokens.
- When a subscriber unsubscribes, Open Paws fires a webhook back to Phase 3's `/phase3/webhook/unsubscribe` endpoint.
- Phase 3's webhook handler updates the subscription table row immediately and logs the event.
- This reuses the platform's existing sender history and domain settings, protecting deliverability and avoiding spam classification.

**Key file:** `platform_handoff.py`

---

## FastAPI Routes (Phase 3 Router)

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/phase3/ingest` | Receives a `SummarizedDocument` from Phase 2, runs validation, writes to DB |
| `GET` | `/phase3/status/{document_number}` | Returns cache status for a given document |
| `POST` | `/phase3/digest/trigger` | Manually triggers the digest build (for testing / admin override) |
| `GET` | `/phase3/digest/{date}` | Returns the compiled digest for a given date (for preview / audit) |
| `POST` | `/phase3/webhook/unsubscribe` | Receives Open Paws unsubscribe webhook, updates subscription table |

---

## Database Tables (Phase 3's Responsibility)

### `summarized_documents`

| Column | Type | Notes |
|---|---|---|
| `document_number` | `TEXT PRIMARY KEY` | Unique federal document ID — idempotency key |
| `publication_date` | `DATE` | From Federal Register API |
| `digest_date` | `DATE` | Date this document appears in the digest |
| `document_type` | `TEXT` | `"Proposed Rule"` / `"Rule"` / `"Notice"` |
| `title` | `TEXT` | Official title |
| `agency` | `TEXT` | Agency name |
| `federal_register_url` | `TEXT` | Source link |
| `comment_deadline` | `DATE` | Nullable — present only if extracted in Phase 1 |
| `confidence_tier` | `TEXT` | `"high_confidence"` or `"confirmation_required"` |
| `status` | `TEXT` | `"approved"` or `"flagged"` |
| `plain_language_summary` | `TEXT` | LLM output |
| `advocacy_relevance` | `TEXT` | LLM output |
| `suggested_actions` | `JSONB` | LLM output — list of strings |
| `suggested_talking_points` | `JSONB` | LLM output — list of strings |
| `disclaimer` | `TEXT` | Hardcoded value |
| `created_at` | `TIMESTAMPTZ` | Row creation timestamp |
| `validation_attempts` | `INT` | Number of correction loops before acceptance |

### `digest_log`

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID PRIMARY KEY` | Auto-generated |
| `digest_date` | `DATE` | Date of digest run |
| `document_count` | `INT` | Number of documents included |
| `zero_result_day` | `BOOLEAN` | Whether circuit breaker fired |
| `sent_at` | `TIMESTAMPTZ` | Timestamp of platform handoff |
| `status` | `TEXT` | `"sent"` / `"failed"` / `"zero_result_sent"` |

---

## Error Handling and Observability

| Scenario | Behavior |
|---|---|
| LLM output fails validation | Bounce back to Phase 2 correction loop with structured error reason; do not persist |
| Database write fails | Raise exception; APScheduler will retry on next scheduled window |
| Zero documents found at digest time | Circuit breaker fires; zero-result digest sent; logged to `digest_log` |
| Open Paws handoff request fails | Log failure to `digest_log`; alert via internal monitoring channel; do not retry automatically (prevent duplicate sends) |
| Unsubscribe webhook fails | Log and re-queue for retry (idempotent operation — safe to repeat) |

---

## Dependencies

```
fastapi
pydantic>=2.0
sqlalchemy[asyncio]
asyncpg            # PostgreSQL async driver
apscheduler
jinja2             # Email templating
httpx              # Async HTTP for Open Paws handoff
python-dotenv      # Environment variable management
```

These are Phase 3-specific additions. Shared project-level dependencies (OpenAI, PyMuPDF, etc.) are managed in the root `requirements.txt` by the project lead.

---

## Environment Variables (Phase 3)

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Supabase / PostgreSQL connection string |
| `OPEN_PAWS_API_URL` | Base URL of Open Paws platform email endpoint |
| `OPEN_PAWS_API_KEY` | Auth key for platform handoff request |
| `PHASE3_WEBHOOK_SECRET` | HMAC secret for verifying Open Paws webhook signatures |
| `DIGEST_SEND_TIME` | Cron expression for APScheduler (default: `30 7 * * *`) |

---

## Integration Contracts with Other Phases

### From Phase 2 → Phase 3

Phase 2 calls `POST /phase3/ingest` with a `SummarizedDocument` JSON body.  
Phase 3 owns the `SummarizedDocument` Pydantic model definition (imported by Phase 2 as a shared schema).  
See [llm_output_contract.md](llm_output_contract.md) for the exact LLM field specifications.

### Phase 3 → Open Paws Platform

Phase 3 sends one `POST` request to Open Paws with the compiled digest bundle.  
Open Paws owns all subscriber management, SMTP credentials, and sending infrastructure.  
Phase 3 only needs the endpoint URL and API key.

### Open Paws → Phase 3 (Webhook)

Open Paws sends unsubscribe events to `POST /phase3/webhook/unsubscribe`.  
Phase 3 verifies the HMAC signature using `PHASE3_WEBHOOK_SECRET` before processing.

---

## What Phase 3 Does NOT Do

- ❌ Call the Federal Register API (Phase 1's responsibility)
- ❌ Call the LLM or run AI classification (Phase 2's responsibility)
- ❌ Manage user accounts or authentication (Open Paws platform)
- ❌ Build or maintain the subscriber list (Open Paws platform)
- ❌ Generate or store URLs from LLM output (all links come from database metadata)
- ❌ Provide legal analysis or advice (hardcoded disclaimer covers this)
