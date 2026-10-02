# Implementation Plan: Mutual Fund FAQ RAG Chatbot

**Based on:** `docs/architecture.md`
**How to use:** Work through the phases in order. Finish the "How to verify" checks for a phase before starting the next one. This document contains no code; it is the plan to guide the build.

**Constraints that apply to every phase**

- Embeddings: `all-MiniLM-L6-v2` (local), the same model for chunks and questions.
- Vector DB: ChromaDB persisted to disk, so ingestion runs once.
- LLM: Groq, with the key in `.env` and never committed.
- Corpus: only the 5 HDFC Groww pages listed in `data/sources.csv`.
- Every answer: at most 3 sentences, one source link, and a "Last updated from sources" line. No advice, no return comparisons, no PII stored.

---

## Phase 1: Project Setup

**What this phase does**
Creates the empty project skeleton so every later phase has a place to live. Sets up dependencies, secret handling and the list of 5 source URLs. No logic yet.

**Files to create**

| File / folder | Purpose |
|---------------|---------|
| `requirements.txt` | Python dependencies (scraping, embeddings, ChromaDB, Groq, dotenv, Streamlit) |
| `.gitignore` | Must ignore `.env`, `chroma_db/`, the virtual environment and cache folders |
| `.env.example` | Template showing the `GROQ_API_KEY` variable name (no real key) |
| `.env` | Your real key, local only, not committed |
| `README.md` | Placeholder for now, filled in at the end |
| `data/sources.csv` | The 5 scheme URLs with scheme name and category |
| `data/` , `src/` , `samples/` | Empty folders as in the architecture's folder structure |
| `src/ingest.py`, `src/guardrails.py`, `src/retriever.py`, `src/generator.py`, `src/formatter.py`, `app.py` | Empty placeholder files |

**How to verify**

- The folder structure matches `docs/architecture.md`.
- A fresh virtual environment installs everything from `requirements.txt` without errors.
- `.env` does not appear in `git status`.
- `sources.csv` lists exactly 5 rows: Large Cap, Flexi Cap, ELSS, Small Cap, Balanced Advantage.

---

## Phase 2: Loading and Chunking

**What this phase does**
Fetches the 5 pages, cleans them to readable text, then splits them into chunks with metadata. Before any chunking logic is written, the agent inspects the cleaned data and proposes a strategy (chunk size, overlap, metadata and why it fits this data), which you approve. All chunks are saved to a readable text file so you can inspect them.

**Files to create**

| File | Purpose |
|------|---------|
| `src/ingest.py` (loading and chunking part) | Reads `sources.csv`, fetches and cleans pages, splits into chunks, attaches metadata |
| `data/raw/` (one text file per scheme) | Cleaned page text, for inspection |
| `data/chunks.txt` | Human-readable list of all chunks with their metadata |

**Metadata each chunk keeps:** scheme name, category, source URL, section, chunk id, last-updated date.

**How to verify**

- Each of the 5 raw files exists and contains the key facts (expense ratio, exit load, minimum SIP, benchmark, risk level, plus lock-in for ELSS). If values are missing, the page probably loads them dynamically and needs a fallback.
- The proposed chunking strategy was written down and approved before the chunking step was built.
- Open `data/chunks.txt` and spot-check: every fact stays next to its label, no chunk mixes two schemes, and metadata is correct on every chunk.

---

## Phase 3: Embedding and Vector Store

**What this phase does**
Turns every chunk into a 384-dimension vector with MiniLM and stores vectors, text and metadata in a persistent ChromaDB collection. Ingestion is one-time: re-running it skips work unless you explicitly ask for a rebuild.

**Files to create / update**

| File | Purpose |
|------|---------|
| `src/ingest.py` (embedding and storage part) | Embeds chunks, writes them to ChromaDB, handles skip-if-exists and a rebuild option |
| `chroma_db/` | Persisted vector store (generated, git-ignored) |

**How to verify**

- Running ingestion prints the number of chunks stored, and it matches the number of chunks in `data/chunks.txt`.
- Running it a second time skips embedding (no duplicate entries).
- After closing and reopening the project, `chroma_db/` still holds the data.
- A quick manual similarity query for a known fact (for example, "ELSS lock-in") returns a chunk from the ELSS page.

---

## Phase 4: Guardrails

**What this phase does**
Adds the checks that run before retrieval, so unsafe or out-of-scope questions never reach the LLM. Three checks: PII, advice/opinion and performance/returns. Each returns a ready-to-show response.

**Files to create**

| File | Purpose |
|------|---------|
| `src/guardrails.py` | PII detection (PAN, Aadhaar, phone, email, OTP-like numbers), advice/opinion detection, return/performance detection |

**Behaviour**

- **PII:** warn the user, discard the input, never log or store it.
- **Advice/opinion:** polite facts-only refusal plus a relevant educational link from the source set.
- **Performance/returns:** no numbers computed or compared; point to the official factsheet link.
- **Factual questions:** pass through untouched.

**How to verify**

- "Should I buy HDFC Small Cap?" gives a polite refusal with a link.
- "Which HDFC fund gave better returns?" gives no comparison and a factsheet link.
- A message containing a PAN-style code, a phone number or an email gets a warning and is not processed.
- Plain factual questions ("What is the minimum SIP for HDFC Flexi Cap?") are not blocked.

---

## Phase 5: Retrieval and LLM Answer

**What this phase does**
Completes the query flow: after guardrails, embed the question with the same MiniLM model, retrieve the top chunks from ChromaDB (filtered by scheme when one is mentioned), have Groq answer from those chunks only, then format the final answer with one citation and the last-updated line.

**Files to create**

| File | Purpose |
|------|---------|
| `src/retriever.py` | Embeds the question, detects a scheme mention, queries ChromaDB for top-k chunks, flags weak matches |
| `src/generator.py` | Calls Groq with a strict prompt (context only, max 3 sentences, no advice, "not available in my sources" fallback) and chains guardrails → retrieve → generate → format |
| `src/formatter.py` | Enforces at most 3 sentences, adds exactly one source link and `Last updated from sources: <date>` |
| `samples/sample_qa.md` | 5 to 10 test queries with the assistant's answers and links |

**How to verify**

- Test questions return the correct scheme and section first: expense ratio, exit load, minimum SIP, ELSS lock-in, benchmark, riskometer.
- A scheme-specific question never surfaces another scheme's chunk first.
- Every answer has at most 3 sentences, exactly one link and a date line.
- A question outside the corpus returns the "not available in my sources" message instead of a guess.
- The Groq key is read only from `.env`; nothing secret is in the code or Git history.
- `samples/sample_qa.md` is filled with results, including the refusal cases from Phase 4.

---

## Phase 6: UI

**What this phase does**
Wraps the pipeline in a tiny Streamlit interface: a welcome line, 3 clickable example questions, a permanent facts-only note and a chat box that shows the answer, its citation link and the last-updated line. Chat state lives only in the session.

**Files to create**

| File | Purpose |
|------|---------|
| `app.py` | Streamlit UI calling the answer pipeline |
| `README.md` (completed) | Setup steps, scope (HDFC + 5 schemes), architecture summary, disclaimer snippet, known limits |

**How to verify**

- The app starts and shows the welcome line, 3 example questions and the note "Facts-only. No investment advice."
- Clicking each example question produces a correct answer with a link and date line.
- An advice question and a PII message both get the right refusal or warning in the UI.
- Restarting the app does not trigger re-ingestion.
- From a fresh clone, following the README (install, add `.env`, run ingestion, start the app) works end to end.
