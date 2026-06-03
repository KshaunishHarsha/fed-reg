# ALDF - RDP Projects: Federal Register Sentinel

## 1. The Core Problem: The Burden of Manual Regulatory Monitoring

The Animal Legal Defense Fund (ALDF) protects animals through impact litigation, legislative drafting, and legal education. Currently, staff members, including attorneys, policy analysts, and legal leads, must manually review the daily publications of the Federal Register to track federal regulatory shifts. This manual review creates a major operational bottleneck.

The stakes are incredibly high because missing a key deadline or an open public comment window hurts advocacy efforts. Therefore, catching every single relevant document is much more important than filtering out minor details. With the Federal Register uploading new documents every single day, critical information easily gets lost inside hundreds of pages of complex, inaccessible government text.

## 2. The Project Objective

To eliminate this manual burden, we are building a reliable, automated notification tool seamlessly integrated within the existing Open Paws platform.

The core features include:

* **Automated Ingestion:** Automatically gathering daily updates directly from the official government feed for key agencies, specifically the USDA, FDA, NOAA, Fish and Wildlife, and NIH.
* **Multi-Layer Filtering:** Using a calibrated multi-layer filter to precisely isolate animal-relevant content.
* **Plain-Language Summaries:** Generating clear summaries that remove dense jargon and highlight advocacy impacts, deadlines, suggested actions, and talking points.
* **Digest Delivery:** Delivering these updates as a clean daily email digest to advocates using your current platform subscription and delivery systems.

## 3. Business Rules and Success Metrics

Currently, your attorneys, policy analysts, and legal leads face a heavy manual burden monitoring the Federal Register. Our goal is to eliminate this manual work by building an automated notification system that ingests daily Federal Register entries, strictly filters for animal-relevant content, and delivers a plain-language email digest directly to your team.

Ultimately, project success will be measured by:

1. A clear reduction in manual tracking hours for your staff.
2. The ability of your team to consistently respond to crucial federal updates before public comment periods close.

---

## Phase 1: The Filtering System

### Purpose

The primary goal of the filtering phase is to reduce the massive daily feed from the Federal Register into a precise, highly relevant collection of animal-related documents before any automated writing begins. Every element of this phase is designed to prioritize complete coverage. For a legal advocacy organization, missing a critical regulatory update is a much greater risk than accidentally including a borderline document.

### Layer 1: Official Government Feed Pre-Filter

The system applies strict parameters directly at the source before downloading any document files. The pipeline connects to the official government feed and immediately requests items published on the current day belonging only to your target agencies (USDA, FDA, NOAA, Fish and Wildlife Service, NIH, and others). It performs this step for both officially published documents and advance public inspection previews. This immediate look-up drops the daily volume from roughly 500 generic documents down to a highly focused group of 20 to 80 agency-specific items at zero processing cost.

### Layer 2: Automatic Noise Removal and Keyword Scoring

Once the initial list is gathered, a two-part cleaning process runs automatically:

* **The Noise Filter:** The system instantly discards specific document categories that are completely irrelevant to animal law regardless of their text content, such as airspace updates, Coast Guard navigation alerts, presidential determinations, and routine administrative meeting notes.
* **Intelligent Keyword Scoring:** The remaining documents are scanned against a specialized vocabulary divided into two distinct levels:
* **Anchor Terms:** Definitive signals of animal relevance, including phrases like *Animal Welfare Act*, *AWA*, *CITES*, *CAFO*, *endangered species*, *factory farming*, or *animal testing*. Finding even one of these terms results in an automatic decision to keep the document. It is flagged as high confidence and sent straight to the next phase.
* **Contextual Terms:** Relevant words that need secondary confirmation, such as *livestock*, *wildlife*, *habitat*, or *processing facility*. The system tallies these terms. If a document crosses a specific point threshold, it is marked as needing confirmation and forwarded to the smart review layer. Anything scoring a zero is dropped immediately.



#### Layer 2a: Full-Text Deep Scanning

This specialized sub-layer activates automatically if a document lacks an official summary paragraph, which is a common issue for advance public inspection previews. Since these advance notices do not contain premade summaries, the pipeline loops through the entire digital text file to find essential keywords.

When an anchor keyword is located anywhere within a 100-page document, the system extracts that specific paragraph along with a protective text buffer on both sides. It stitches these extracted segments together into a single, highly concentrated context block. If no keywords are found anywhere in the text, the document is safely discarded; otherwise, this concentrated text block replaces the missing summary to act as the primary input for the next layer.

### Layer 3: Smart Verification and Target Extraction

Documents that survive the initial keyword scans are sent to a highly efficient artificial intelligence check. The behavior of this layer changes based on the safety flags set during the keyword phase:

* **High Confidence Documents:** Since their legal relevance was already proven by the keyword search, the system does not ask the intelligence model to decide whether to keep them. Instead, the model is strictly used to extract critical operational details, such as the regulation category and key milestones like public comment deadlines or effective dates.
* **Confirmation Required Documents:** For borderline files, the model evaluates the context to make an explicit decision on relevance. If it confirms the document matches your advocacy focus, it extracts the identical calendar dates and structural categories.

> **Audit Note:** Every single decision, keyword tally, and verification reason is saved into a permanent audit log to ensure complete transparency.

---

## Phase 2: The Summarization and Generation System

### Purpose

This phase takes the confirmed regulatory files and transforms them into clear, advocate-facing newsletter updates. To maximize accuracy and eliminate processing lag, the system automatically routes documents down one of three processing tracks based on their exact page length.

### Document Routing Paths

The pipeline tracks the official page count of each file and estimates length using a standard metric of roughly 700 words per page to select the ideal path:

* **Tier 1 (Short Files under 15 Pages):** This track handles informational notices and minor adjustments. The system passes the clean text directly to the model to generate a structured overview in a single step.
* **Tier 2 (Medium Files from 15 to 50 Pages):** This track processes standard proposed regulations and major agency announcements. To prevent the model from getting distracted by low-signal text, built-in code automatically strips out administrative boilerplate, including historical background summaries, old citation lists, signature blocks, and closing legal fine print. It retains only the core proposals and date sections, creating a highly focused text segment that guarantees excellent summary accuracy.
* **Tier 3 (Long Monster Files over 50 Pages):** This track manages massive cross-department policy overhauls. Instead of overwhelming the model with thousands of pages of text, the pipeline reuses the precision context blocks compiled during the Phase 1 deep scan. The system attaches a special instruction note informing the model that it is reviewing a pre-extracted segment of a larger document, generating a reliable summary without massive token costs.

### Uniform Output Standards

No matter which path a document takes, the resulting text must fit an identical, strict layout before it is accepted. The system automatically enforces maximum lengths and explicit content sections, requiring:

* A plain-language summary limited to 2 or 3 sentences with no dense administrative jargon.
* A clear breakdown of why the shift matters to your policy and litigation teams.
* A maximum of 3 suggested advocacy actions, capped at 25 words per bullet point.
* A maximum of 3 targeted talking points to aid public comment submissions, capped at 25 words per bullet point.
* Normalized calendar deadlines and a hardcoded legal disclaimer.

If an update fails to meet these formatting rules, the system automatically runs a quick correction loop to fix the layout instantly.

---

## Phase 3: Post-Processing and Email Delivery

### Purpose

This final phase takes the completed summaries, verifies their layout, caches them permanently in your database, organizes them into an elegant daily newsletter layout, and safely hands execution over to your current platform infrastructure. This protects your communication channel from spam filters and ensures delivery remains consistent.

### Step 1: Automated Quality Review and Correction

Before writing any data to a permanent drive, the system passes the text through a strict verification checklist. It verifies that all required data fields exist, date formats strictly match standard calendar styles, and individual bullet points do not exceed word count limits. If any minor formatting errors are detected, the pipeline catches the trace error and pipes it back as an urgent system correction note to the model, fixing structural anomalies on the fly.

### Step 2: Database Storage and Automated Fail-Safe Routine

Once a summary passes its health check, it is committed to your secure database using its official federal document number as a unique key. This locks the summary into a permanent cache. If the server restarts or an analyst reloads the page, the system reads from this cache for free instead of paying to recreate the text.

### Step 3: Digest Compilation and Layout Design

The system triggers the final layout builder daily at 7:30 AM once all filtering and writing tasks have fully settled. It queries the database to gather all approved entries for that calendar date.

* **Circuit Breaker:** If no matching documents are found for the day, a circuit breaker trips, and a minimal digest is sent confirming that no animal-relevant federal activity was identified that day.

If documents are present, the system loops through the entries and compiles a dual-layer email package containing both a visual HTML format and an alternative plain-text version for mobile screens. The engine organizes the layout into clean, distinct sections sorted by urgency:

* **Section A (High Priority):** Proposed rules with active public comment periods, emphasizing closing dates.
* **Section B (Watchdog Monitoring):** Finalized rules and standard informational notices.
* **Section C (Potential Matches):** Borderline unreviewed items marked with a clear warning badge.

The system hardcodes the mandatory disclaimer at the base of every document update and inside the master footer, while using direct database values to build clean outbound links to the source portals, bypassing model hallucinations entirely.

### Step 4: Secure Platform Handoff and Distribution

The pipeline packages the completed newsletter layout into a single delivery bundle and passes it to your pre-existing Open Paws platform email system via one secure request, instructing it to distribute the layout to your active subscriber segment.

The sending module ensures that standard opt-out data is embedded into the hidden mail headers, allowing users to unsubscribe cleanly. This interaction triggers a webhook to update your subscription tables instantly, reusing your established sender history and official settings to protect domain health and prevent spam blocks.

---

## Federal Register Sentinel: Technology Stack

| Technology Component | Operational Layer | Why This Option |
| --- | --- | --- |
| **Federal Register Public API** | Ingestion Layer | Web scraping is unreliable and costly to maintain. Using the official public feed lets the system filter files directly at the source by date and agency, instantly narrowing hundreds of entries down to 20–80 items. |
| **PyMuPDF** | Full-Text Extraction | Advanced image processing tools are unnecessary because government documents are already in clean, digital text. This tool instantly reads full text to scan for keywords, saving money on processing infrastructure. |
| **OpenAI gpt-4o-mini** | Classification & Summarization | Larger models are expensive and slow. Since smart keyword filters handle the heavy lifting first, this lighter model is only called for highly relevant documents to maximize cost efficiency and speed. |
| **Pydantic v2 & Instructor** | Validation & Self-Correction | Standard text readers break when AI creates unpredictable text formats (e.g., words instead of dates). This setup double-checks structures and instantly requests corrections from the model. |
| **Native HTML Parsing & Regex** | Boilerplate Pruning | Passing massive 50+ page documents directly to AI causes context confusion. Because government documents use standard web formatting, simple built-in code can remove boilerplate and signatures for free. |
| **Supabase / PostgreSQL** | Persistence & Idempotency Caching | Secure, structured storage is required to track every file and avoid duplicate emails. Logs documents under their official federal index number to pull from cache if tasks run twice. |
| **APScheduler** | Background Task Execution | Runs the pipeline precisely at 7:30 AM once all documents have finished processing, and includes an automatic safety check that safely handles zero-result days. |
| **Existing Open Paws Platform** | Auth, Subscriptions & Broadcast | Rebuilding user accounts and email networks is outside our scope. Packaging summaries into a single delivery bundle allows a quick handoff to your existing system, preserving sender history. |

---

## What Is Included and Why

* **Daily monitoring of both published documents and advance public inspection previews:** Published documents are the official record, but public inspection previews appear 1–2 business days earlier, giving your attorneys more lead time before comment deadlines close.
* **Agency-level filtering at the source:** Before downloading anything, the system restricts its search to only USDA, FDA, NOAA, Fish and Wildlife, and NIH, eliminating irrelevant content immediately at zero cost.
* **A two-tier keyword system:** The vocabulary is split into high-certainty Anchor Terms (which automatically flag a document as relevant) and supporting Contextual Terms (which contribute to a score for secondary review) to ensure important documents are never accidentally discarded.
* **Full-text scanning for documents without a summary paragraph:** Advance public inspection filings do not include a pre-written summary by default. The system reads the full text, locates relevant passages, and assembles its own focused summary block.
* **AI verification and structured data extraction:** A cost-efficient AI model confirms relevance for borderline items and extracts key operational details (regulation category, deadlines, hearing dates). For pre-confirmed documents, the AI is skipped for routing decisions and used only for extraction.
* **Three-path summarization based on document length:** Short notices are processed in a single pass; medium-length rules have low-signal administrative text stripped; very long documents reuse the pre-extracted context blocks to avoid high token costs.
* **Automated formatting checks with self-correction:** Every summary is checked against strict rules. If it has the wrong date format or too many bullet points, the system automatically requests a correction from the AI before it reaches the database.
* **Permanent storage with duplication prevention:** Each document is saved under its unique federal document number, ensuring that if the system runs twice, it reads from storage rather than regenerating text.
* **A daily email digest organized by urgency:** Approved summaries are compiled into a structured newsletter each morning with active public comment windows displayed first and the legal disclaimer fixed into every footer.
* **Delivery through your existing Open Paws platform:** The system hands the completed digest to Open Paws as a single package, completely bypassing the need to rebuild unsubscribe management or sender reputation infrastructure.

---

## What Is Excluded and Why

* **A human review queue for borderline documents:** Removed because it requires your team to take daily action inside an admin interface to prevent delays, which creates the exact operational burden the tool is designed to eliminate. Borderline cases are instead handled confidently via inclusive keyword rules and AI.
* **Embedding-based semantic search:** A more complex filtering approach using AI-generated document fingerprints was removed because the keyword system combined with AI verification handles the filtering accurately at this volume without ongoing technical maintenance.
* **Automatic promotion of unreviewed items:** This fallback mechanism was omitted along with the review queue itself. The simpler two-status design (documents are either approved or flagged as failed) is more reliable and requires zero staff intervention.
* **A zero-result silent shutdown:** If no relevant documents are found, the system does not go quiet. A minimal digest is sent to confirm that no animal-relevant activity was identified, letting your team easily distinguish a quiet day from a system problem.
* **State, international, and legal analysis content:** These are explicitly outside the scope defined in the project brief and are not part of this build.
* **Real-time alert delivery and live streaming webhooks:** Continuous live trackers are omitted because the government feed updates once per day in a single bulk upload; running one scheduled morning task maintains optimal freshness while keeping compute costs low.
* **Distributed queue networks and external message brokers:** Managing complex background task coordination systems is omitted, as the background job is called only once daily.