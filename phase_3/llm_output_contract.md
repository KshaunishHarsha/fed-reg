# Phase 3 — LLM Output Contract

## Overview

This document defines the **exact structured output** that Phase 2's summarization system must produce and hand off to Phase 3. Phase 3 does **not** call the LLM itself — it only **receives**, **validates**, and **persists** this payload.

The contract is intentionally strict: Phase 2 is responsible for retrying or self-correcting until its output fully conforms to the schema below before passing it downstream.

> **Isolation Boundary:**  
> Everything inside `<regulatory_document_summary>` is **LLM-generated only** — no raw API fields, no federal register metadata, no agency names fetched directly from the government feed. Those values live in a separate, structured envelope (see Phase 3 `README.md`). This separation eliminates hallucination risk on factual fields and keeps the two concerns cleanly decoupled.

---

## XML Schema

```xml
<regulatory_document_summary>
    <plain_language_summary>...</plain_language_summary>

    <advocacy_relevance>...</advocacy_relevance>

    <suggested_actions>
        <action>...</action>
        <action>...</action>
        <action>...</action>
    </suggested_actions>

    <suggested_talking_points>
        <point>...</point>
        <point>...</point>
        <point>...</point>
    </suggested_talking_points>

    <disclaimer>This summary is informational only and does not constitute legal advice.</disclaimer>
</regulatory_document_summary>
```

---

## Field Definitions

### `<plain_language_summary>`

| Attribute | Specification |
|---|---|
| **Type** | Single block of plain prose |
| **Length** | 2–3 sentences maximum |
| **Purpose** | Replaces dense government jargon with clear, advocate-facing language describing what the regulation does |
| **Constraints** | No citations, no document numbers, no agency-specific abbreviations unexplained to a layperson |

**Example:**
```
The USDA is proposing a new rule that would strengthen welfare standards for
pigs in commercial farming operations. The rule targets overcrowding and
transport conditions and opens a 60-day public comment window ending July 15,
2026.
```

---

### `<advocacy_relevance>`

| Attribute | Specification |
|---|---|
| **Type** | Single block of plain prose |
| **Length** | 1–2 sentences maximum |
| **Purpose** | Explains *specifically* why this document matters to ALDF's litigation and policy teams — the advocacy angle, not a re-summary of the rule |
| **Constraints** | Must connect to one of: animal welfare, endangered species, factory farming, laboratory animal use, or similar ALDF focus areas |

**Example:**
```
This directly impacts ALDF's ongoing litigation strategy around CAFO welfare
standards and creates a live public comment opportunity for staff to formally
submit legal arguments.
```

---

### `<suggested_actions>`

| Attribute | Specification |
|---|---|
| **Type** | Ordered list of `<action>` child elements |
| **Count** | Minimum 1, maximum 3 |
| **Per-item length** | ≤ 25 words per `<action>` element |
| **Purpose** | Concrete, specific steps an ALDF advocate or attorney can take right now |
| **Constraints** | Must be action-oriented (start with a verb). No generic filler like "Stay informed." Must reference the specific document context. |

**Example:**
```xml
<suggested_actions>
    <action>Submit a formal comment to the USDA docket by July 15 opposing the exemptions in Section 3(b).</action>
    <action>Coordinate with litigation team to assess alignment with pending CAFO case filings.</action>
    <action>Share the public comment link with grassroots partner organizations for amplified response.</action>
</suggested_actions>
```

---

### `<suggested_talking_points>`

| Attribute | Specification |
|---|---|
| **Type** | Ordered list of `<point>` child elements |
| **Count** | Minimum 1, maximum 3 |
| **Per-item length** | ≤ 25 words per `<point>` element |
| **Purpose** | Ready-to-use language for public comment submissions, press statements, or internal briefings |
| **Constraints** | Must be declarative statements (not questions). Must be substantive and specific to this document. |

**Example:**
```xml
<suggested_talking_points>
    <point>Current transport standards leave millions of pigs without enforceable protections during cross-state shipment.</point>
    <point>The proposed exemptions for small operations undermine the rule's stated welfare goals.</point>
    <point>ALDF urges the USDA to adopt the stronger welfare metrics recommended by independent veterinary experts.</point>
</suggested_talking_points>
```

---

### `<disclaimer>`

| Attribute | Specification |
|---|---|
| **Type** | Fixed, hardcoded string |
| **Value** | `This summary is informational only and does not constitute legal advice.` |
| **Mutability** | **Immutable.** The Phase 2 prompt must instruct the model to output this exact string verbatim. Phase 3 validation will reject any deviation. |

---

## Actionability Signals Embedded in the Payload

The Phase 2 prompt is responsible for ensuring the LLM encodes the following actionability signals inside the fields above (not as separate tags). Phase 3's quality checker reads for their presence:

| Signal | Where It Appears | What Phase 3 Checks |
|---|---|---|
| Open public comment period | `plain_language_summary` and/or `suggested_actions` | Deadline date in ISO-like format (`Month DD, YYYY`) must be detectable |
| Upcoming hearing | `plain_language_summary` | Hearing date must be present if extracted in Phase 1 |
| Pending decision / finalization | `advocacy_relevance` | Language indicating regulatory stage (proposed / final / interim) must be present |
| Direct link placeholder | NOT in XML — links are pulled from the separate metadata envelope | Phase 3 joins this from the database record, never from LLM text |

> **Critical Rule:** The LLM output must **never** contain a hyperlink or URL. All outbound links (Federal Register notice, docket page, agency portal) are stored in the database metadata record and injected by Phase 3's email template engine. This prevents hallucinated URLs from reaching subscribers.

---

## Full Envelope: What Phase 2 Posts to Phase 3

Phase 2 calls `POST /phase3/ingest` with a JSON body that matches the `IngestPayload` model
defined in `phase_3/models.py`. This is the **source of truth** — Phase 2 must build
a payload that deserializes into this structure without errors.

```python
# phase_3/models.py — IngestPayload (do not modify; owned by Phase 3)

class DocumentRecord(BaseModel):
    """
    Metadata from the `documents` table. All values come from the Federal
    Register API + Phase 1 extraction. Zero LLM-generated content here.
    """
    document_number:     str                   # e.g. "2026-09841" — PK in documents table
    title:               str                   # official title from API
    agency_names:        Optional[List[str]]   # e.g. ["USDA", "APHIS"]
    type:                Optional[str]         # "RULE" | "PRORULE" | "NOTICE"
    regulation_category: Optional[str]         # "Proposed Rule" | "Final Rule" | "Notice" | "Other"
    comments_close_on:   Optional[date]        # public comment deadline (if applicable)
    effective_on:        Optional[date]        # rule effective date (if applicable)
    html_url:            Optional[str]         # Federal Register source URL
    comment_url:         Optional[str]         # docket ID or regulations.gov URL
    publication_date:    date                  # ISO date from API
    confidence:          Optional[str]         # "HIGH" | "NEEDS_CONFIRMATION"
    pipeline_state:      str = "SUMMARY_GENERATED"


class IngestPayload(BaseModel):
    """
    Full envelope posted to POST /phase3/ingest by Phase 2.
    Phase 3 parses xml_summary_blob → ValidatedSummary internally.
    The raw blob is written to the `summaries` table as-is.
    """
    document_record:  DocumentRecord   # populated from the documents table row
    xml_summary_blob: str              # exact XML string from Phase 2 LLM output
```

**Important:** Phase 2 does **not** need to post the parsed LLM fields as individual
JSON keys. It posts `xml_summary_blob` as a raw XML string, exactly as the LLM returned
it. Phase 3 handles the parsing internally via `xml_parser.py`.

---

## Validation Rules Phase 3 Enforces

Phase 3 parses `xml_summary_blob` and validates all fields before writing to the database.
Failures on rules 1–6 are returned to Phase 2's correction endpoint as a structured
`error_detail` string so the LLM can be re-prompted. Rule 7 failures are silently corrected.

| # | Field | Rule | On Failure |
|---|---|---|---|
| 1 | `plain_language_summary` | Non-empty; ≤ 3 sentences | Bounce to Phase 2 correction |
| 2 | `advocacy_relevance` | Non-empty; ≤ 2 sentences | Bounce to Phase 2 correction |
| 3 | `suggested_actions` | 1–3 items; each ≤ 25 words | Bounce to Phase 2 correction |
| 4 | `suggested_talking_points` | 1–3 items; each ≤ 25 words | Bounce to Phase 2 correction |
| 5 | `disclaimer` | Must exactly equal `"This summary is informational only and does not constitute legal advice."` | Bounce to Phase 2 correction |
| 6 | All LLM fields | No `http://` or `https://` URLs anywhere | URL stripped silently, event logged; **no bounce** |

Phase 2 correction endpoint: `POST {PHASE2_CORRECTION_URL}` — Phase 3 sends the
`error_detail` string back; Phase 2 is responsible for re-running the LLM with it as
a system correction note. Maximum 2 correction cycles (3 total attempts).

---

## Why XML (Not JSON)?

The project plan specifies Pydantic v2 + Instructor for structured output. The XML
envelope is Phase 2's **prompt-level enforcement layer** — it prevents the model from
free-forming its response and makes parsing deterministic with a single `ElementTree`
pass. `xml_parser.py` in Phase 3 handles the parse. The XML schema above is the single
source of truth for what the LLM may and may not produce.
