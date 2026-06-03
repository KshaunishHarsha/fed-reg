# ALDF - RDP Projects

## Federal Register Email Notifications

### Summary of Project
[cite_start]The Animal Legal Defense Fund (ALDF) is a nonprofit legal advocacy organization advancing animal protection through impact litigation, legislation drafting, and legal education. [cite: 39]

[cite_start]Their staff—attorneys, policy analysts, and legal leads—need timely visibility into federal regulatory activity without manually reviewing the Federal Register daily. [cite: 40]

[cite_start]We are building a notification feature that ingests newly published Federal Register entries daily, filters for animal-related content, generates plain-language summaries with advocacy guidance, and delivers email digests via existing platform infrastructure. [cite: 41]

### Project Scope

#### In scope:
* [cite_start]**Daily automated ingestion** of Federal Register content via public API. [cite: 45]
* [cite_start]**Animal-relevance filtering** (hybrid approach: keyword matching + AI classification). [cite: 45]
* [cite_start]**AI-generated plain-language summaries** including: advocacy relevance, deadlines, suggested actions, and links for source verification. [cite: 45]
* [cite_start]**Actionability layer:** identifies open comment periods, upcoming hearings, pending decisions. [cite: 46]
* [cite_start]**Agency-specific monitoring** (USDA, FDA, NOAA, Fish & Wildlife, NIH, others TBD). [cite: 47]
* [cite_start]**Integration with existing Open Paws platform:** authentication, subscription management, email delivery. [cite: 47, 48]

#### Out of scope:
* [cite_start]State or international regulatory tracking. [cite: 50]
* [cite_start]Rebuilding existing user/account infrastructure. [cite: 51]
* [cite_start]Legal advice or formal legal analysis. [cite: 51]

### Key Features & User Experience

#### User Flow:
1. [cite_start]User subscribes via existing Open Paws platform registration. [cite: 53]
2. [cite_start]Daily digest delivered by email containing relevant Federal Register items. [cite: 54]
3. [cite_start]Each item includes: title, plain-language summary, advocacy relevance, deadlines, responsible agency, actionability assessment, suggested talking points, and direct link to source. [cite: 55]
4. [cite_start]All summaries carry disclaimer: informational only, not legal advice. [cite: 56]

[cite_start]**Success Metrics:** Advocates identify and respond to relevant federal actions before deadlines; reduction in manual monitoring burden. [cite: 57]

### Use Cases & Business Rules
* [cite_start]**Use Case 1:** Advocate catches open public comment period before deadline via digest. [cite: 59]
* [cite_start]**Use Case 2:** Advocacy org monitors specific agencies for relevant rulemaking. [cite: 59]
* [cite_start]**Use Case 3:** Researcher reviews historical notices and summaries. [cite: 59]

#### Rules:
* [cite_start]Every item links directly to the original Federal Register notice and includes publication date and agency. [cite: 60]
* [cite_start]Actionability assessments are clearly labeled as informational. [cite: 61]
* [cite_start]Existing unsubscribe/subscription flows must be reused. [cite: 61]

### Security Requirements
* [cite_start]**Tier 2 - Standard:** System handles email addresses, subscription preferences, and public government data only. [cite: 63]
* Existing platform authentication and security controls assumed sufficient. [cite_start]API key protection, rate limiting, and audit logging required for automated content generation. [cite: 64]

### Timeline
[cite_start]*Details covered in internal RDP program design.* [cite: 66]

* [cite_start]**Week 1:** Client alignment, solution design, and early prototype. [cite: 67]
* [cite_start]**Week 2:** Client validates prototype; build begins if approved. [cite: 67]
* [cite_start]**Weeks 3–5:** Core product built, tested, and refined in weekly sprints. [cite: 67, 68]
* [cite_start]**Week 6:** Product launched, client onboarded, documentation complete. [cite: 68]
* [cite_start]**Week 7:** Final quality pass, handoff package delivered, cohort showcase. [cite: 68]

### Tools and Resources
* [cite_start]Federal Register public API (federalregister.gov). [cite: 70]
* [cite_start]Existing Open Paws platform (auth, subscriptions, email delivery). [cite: 71]
* [cite_start]OpenAI or equivalent LLM for summarization and classification. [cite: 71]
* [cite_start]Background job scheduler (TBD). [cite: 71]
* [cite_start]PostgreSQL or equivalent database. [cite: 72]
* [cite_start]GitHub (open source repository). [cite: 72]