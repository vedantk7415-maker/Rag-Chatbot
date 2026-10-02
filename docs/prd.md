# PRD: Mutual Fund FAQ Assistant (Facts-Only RAG Chatbot)

**Context:** Class demo
**Source brief:** `problemStatement.txt`

---

## 1. Overview

A small RAG (Retrieval-Augmented Generation) chatbot that answers **factual** questions about HDFC Mutual Fund schemes (expense ratio, exit load, minimum SIP, ELSS lock-in, riskometer, benchmark, statement downloads) using **only the provided source pages**. Every answer carries exactly one source link. The bot gives **no investment advice**.

## 2. Goals

- Answer repetitive mutual fund fact questions accurately from a fixed, public corpus.
- Show a working end-to-end RAG pipeline: **ingestion (Load → Chunk → Embed → Store)** and **query (Question → Embed → Retrieve → LLM → Answer)**.
- Be transparent: one citation per answer and a "Last updated from sources" date.
- Politely refuse opinion, advice and portfolio questions.

## 3. Non-Goals

- No buy/sell/hold recommendations or portfolio guidance.
- No return computation or scheme-vs-scheme performance comparison (link to the official factsheet instead).
- No user accounts, and no storage of any personal data.
- No live data fetching at query time; answers come from the ingested snapshot only.

## 4. Target Users

- Retail investors comparing schemes who need quick facts.
- Support/content teams answering repetitive MF questions.

## 5. Scope

**AMC:** HDFC Mutual Fund
**Schemes (5, Direct Growth):**

| # | Category | Source URL |
|---|----------|-----------|
| 1 | Large Cap | https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth |
| 2 | Flexi Cap | https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth |
| 3 | ELSS | https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth |
| 4 | Small Cap | https://groww.in/mutual-funds/hdfc-small-cap-fund-direct-growth |
| 5 | Balanced Advantage (Hybrid) | https://groww.in/mutual-funds/hdfc-balanced-advantage-fund-direct-growth |

These 5 URLs are the entire corpus. Answers must be grounded in them.

## 5.1 Supported Question Types

- Expense ratio of `<scheme>`
- Exit load
- Minimum SIP / lump sum
- ELSS lock-in period
- Riskometer rating
- Benchmark index
- How to download a capital-gains / account statement

## 6. Functional Requirements

| ID | Requirement |
|----|-------------|
| FR1 | Answer factual queries about the 5 schemes using retrieved chunks only. |
| FR2 | Every answer includes **one** clear citation link (the source page of the supporting chunk). |
| FR3 | Answers are **≤ 3 sentences**. |
| FR4 | Every answer ends with: `Last updated from sources: <date>`. |
| FR5 | Opinionated or advice questions (e.g., "Should I buy/sell?") get a polite facts-only refusal plus a relevant educational link. |
| FR6 | Performance or return questions are not computed or compared; the bot points to the official factsheet link. |
| FR7 | If the answer is not in the retrieved context, the bot says it doesn't have that information rather than guessing. |
| FR8 | The bot does not accept or store PII (PAN, Aadhaar, account numbers, OTPs, emails, phone numbers). If the user types any, the bot warns and does not process or persist it. |

## 7. UI Requirements (Tiny UI)

- Welcome line.
- 3 clickable example questions (e.g., "What is the expense ratio of HDFC Flexi Cap?", "What is the ELSS lock-in period?", "What is the minimum SIP for HDFC Large Cap?").
- Visible note: **"Facts-only. No investment advice."**
- Chat input and answer area showing the answer, the citation link and the last-updated line.

## 8. Technical Constraints

| Area | Decision |
|------|----------|
| Embedding model | `sentence-transformers/all-MiniLM-L6-v2` (local, no API key, 384-dim). The **same model** embeds both chunks and user questions. |
| Vector DB | **ChromaDB**, persisted to disk. Ingestion runs once, not on every restart. |
| LLM | **Groq**. API key stored in `.env`, never committed to Git (`.env` in `.gitignore`). |
| Chunking | Decided by the AI agent (Cursor / OpenCode / Claude Code), see section 10. |
| Sources | Public sources only. No app back-end screenshots. |

## 9. Architecture

### 9.1 Ingestion (run once)

```
Load (5 URLs) → Chunk → Embed (MiniLM) → Store (ChromaDB on disk)
```

1. **Load:** fetch and clean text from the 5 source pages.
2. **Chunk:** per the agreed strategy (section 10).
3. **Embed:** all-MiniLM-L6-v2, 384-dim vectors.
4. **Store:** persist vectors plus metadata in ChromaDB. Also write all chunks to a readable `chunks.txt` for inspection.

### 9.2 Query (per question)

```
Question → Guardrails → Embed → Retrieve top-k chunks → LLM (Groq) → Answer + citation
```

1. **Guardrails:** detect PII, advice/opinion intent and performance/return intent before retrieval.
2. **Embed:** same MiniLM model.
3. **Retrieve:** top-k chunks from ChromaDB (k to be tuned, start with 3 to 5), optionally filtered by scheme metadata.
4. **Generate:** Groq LLM answers using only retrieved context, with a system prompt enforcing ≤ 3 sentences, one citation, no advice and no guessing.
5. **Respond:** answer + one source URL + "Last updated from sources: <date>".

## 10. Chunking Strategy (Agent-Proposed, Before Any Code)

Before writing code, the agent must inspect the scraped data and **propose** a strategy covering:

- **Why** it suits this data (e.g., small structured fact pages with key-value style fields like expense ratio, exit load, SIP minimum).
- **Chunk size and overlap** (specific numbers).
- **Metadata kept per chunk**, at minimum: `scheme_name`, `category`, `source_url`, `section`, `last_updated`.

All chunks are saved to a readable `.txt` file so they can be reviewed.

## 11. Constraints & Guardrails

- **Public sources only:** no app back-end screenshots, no third-party blog sources.
- **No PII:** never accept or store PAN, Aadhaar, account numbers, OTPs, emails or phone numbers.
- **No performance claims:** don't compute or compare returns; link to the official factsheet.
- **Clarity:** ≤ 3 sentences per answer, one citation, last-updated line.

## 12. Deliverables

1. **Working prototype** (app/notebook link) or a demo video of ≤ 3 minutes if hosting isn't possible.
2. **Source list** (CSV/MD) of the 5 URLs used.
3. **README** with setup steps, scope (AMC + schemes) and known limits.
4. **Sample Q&A file** with 5 to 10 queries, the assistant's answers and links.
5. **Disclaimer snippet** used in the UI (facts-only, no advice).

## 13. Sample Test Queries

| Type | Example |
|------|---------|
| Factual | "What is the expense ratio of HDFC Flexi Cap?" |
| Factual | "What is the lock-in period of HDFC ELSS Tax Saver?" |
| Factual | "Minimum SIP for HDFC Small Cap?" |
| Factual | "What is the benchmark of HDFC Large Cap?" |
| Factual | "How do I download my capital-gains statement?" |
| Refusal (advice) | "Should I buy HDFC Small Cap?" |
| Refusal (performance) | "Which HDFC fund gave better returns?" |
| Out of scope | "What is the NAV of a non-HDFC fund?" |
| PII | "My PAN is XXXXX, show my holdings" |

## 14. Acceptance Criteria

- [ ] Ingestion runs once and ChromaDB persists to disk; restart does not re-ingest.
- [ ] `chunks.txt` exists and is human-readable, with the chunking rationale documented.
- [ ] All answers are ≤ 3 sentences, with exactly one citation link and a last-updated line.
- [ ] Advice and performance questions are refused politely with an educational/factsheet link.
- [ ] PII is not accepted or stored.
- [ ] Groq key lives only in `.env`, which is git-ignored.
- [ ] UI shows welcome line, 3 example questions and the "Facts-only. No investment advice." note.
- [ ] README, source list, sample Q&A and disclaimer are included.

## 15. Risks & Known Limits

- **Source type:** The brief asks for official AMC/SEBI/AMFI pages but lists Groww URLs, a third-party platform. Confirm this is acceptable for the demo, or add AMC pages (e.g., hdfcfund.com scheme pages, SID/KIM) as supplements.
- **Stale data:** pages are snapshotted at ingestion, so values like expense ratio can change. The "Last updated" line mitigates this.
- **Scraping reliability:** some page values load dynamically and may be missing from a plain scrape.
- **Retrieval confusion:** similar fields across 5 schemes can cause wrong-scheme answers. Mitigate with scheme-name metadata and filtering.
- **Hallucination:** mitigated by a strict context-only system prompt and a "not found" fallback.

## 16. Open Questions

- Which UI framework (Streamlit, Gradio or a simple web page)?
- Which Groq model to use?
- Should official AMC pages be added alongside the 5 Groww URLs?
- Where will the demo be hosted (or will it be a recorded video)?
