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

## Full Envelope: What Arrives at Phase 3

The LLM XML payload travels **inside** a larger Python dataclass / Pydantic model that carries the non-LLM factual fields alongside it. Phase 3 receives the full envelope:

```python
class SummarizedDocument(BaseModel):
    # --- Metadata (fetched directly from Federal Register API — NOT from LLM) ---
    document_number: str          # e.g. "2026-09841" — used as unique DB key
    publication_date: date        # ISO date from API
    document_type: str            # "Proposed Rule" | "Rule" | "Notice"
    title: str                    # Official title from API
    agency: str                   # e.g. "USDA", "FDA"
    federal_register_url: str     # Direct source link — never from LLM
    comment_deadline: Optional[date]  # Parsed from Phase 1 extraction
    confidence_tier: str          # "high_confidence" | "confirmation_required"

    # --- LLM Output (parsed from XML above) ---
    plain_language_summary: str
    advocacy_relevance: str
    suggested_actions: List[str]          # 1–3 items, ≤ 25 words each
    suggested_talking_points: List[str]   # 1–3 items, ≤ 25 words each
    disclaimer: str                       # Must equal hardcoded string exactly
```

Phase 3's validation step runs against `SummarizedDocument` as a whole — rejecting the envelope if either the metadata or the LLM fields are malformed.

---

## Validation Rules Phase 3 Enforces

Before writing to the database, Phase 3 checks:

1. **`plain_language_summary`** — non-empty, ≤ 3 sentences (sentence count heuristic: split on `.!?`)
2. **`advocacy_relevance`** — non-empty, ≤ 2 sentences
3. **`suggested_actions`** — list length 1–3; each item ≤ 25 words
4. **`suggested_talking_points`** — list length 1–3; each item ≤ 25 words
5. **`disclaimer`** — exact string match to `"This summary is informational only and does not constitute legal advice."`
6. **`comment_deadline`** — if present in metadata envelope, must also be referenced (as human-readable date) somewhere in `plain_language_summary` or `suggested_actions`
7. **No URLs** — regex scan of all LLM fields; any `http://` or `https://` triggers automatic correction loop

If validation fails on items 1–6, Phase 3 sends the failed summary back to the Phase 2 correction endpoint with the specific rule violation noted. If the URL check (item 7) fails, the URL is stripped silently and the event is logged.

---

## Why XML (Not JSON)?

The project plan specifies Pydantic v2 + Instructor for structured output. The XML envelope is Phase 2's **prompt-level enforcement layer** — it prevents the model from free-forming its response and makes parsing deterministic with a single `ElementTree` pass. Instructor then maps the parsed XML into the `SummarizedDocument` Pydantic model for downstream use. The XML schema is the single source of truth for what the LLM may and may not produce.
