# HDFC Mutual Fund Facts Bot

A facts-only RAG chatbot built for a class demonstration. It answers questions
about five HDFC mutual fund schemes using **only** an ingested corpus of public
pages — no training data, no third-party blogs, no invented facts.

> **Educational demo. Not investment advice.**

---

## What it does

Ask about a scheme, get a short factual answer with a source link and the date the
data was collected:

```
You:  What is the expense ratio of HDFC Large Cap?
Bot:  The expense ratio of HDFC Large Cap Fund - Direct Growth is 1.04%.

      Source: https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth
      Last updated from sources: 2026-10-02
```

Every answer is guaranteed to be **at most 3 sentences**, carry **exactly one
citation link**, and end with the collection date. These are enforced in code, not
merely requested in a prompt.

---

## Quickstart

Requires Python 3.10+ and a free [Groq API key](https://console.groq.com/keys).

```bash
# 1. Environment
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# 2. API key  (copy the example, then paste your key after the =)
copy .env.example .env

# 3. Ingest the corpus — run ONCE
python src/ingest.py

# 4. Launch the app
streamlit run app.py
```

Step 3 downloads the embedding model (~90 MB) on first run and takes a minute or
two. It is genuinely one-time: afterwards the script prints
`[embed] already up to date: 46 vectors` and skips straight to step 4.

Optional flags:

```bash
python src/ingest.py --rebuild                        # re-fetch pages + re-embed
python src/ingest.py --query "ELSS lock-in" --top-k 3 # inspect retrieval by hand
python src/generate_samples.py                         # regenerate samples/sample_qa.md
python samples/ui_test.py                              # headless test of the UI
```

---

## Architecture

```
question
   │
   ▼
┌─────────────┐  blocked? ──► canned refusal, LLM never called
│ guardrails  │  PII · advice · performance
└──────┬──────┘
       │ allowed
       ▼
┌─────────────┐  embed question with MiniLM (same model, same normalisation)
│  retriever  │  exact metadata filter when a scheme is named
└──────┬──────┘
       │ top-5 chunks
       ▼
┌─────────────┐  answer from context only, max 3 sentences, no URLs
│  generator  │  Groq · openai/gpt-oss-120b · temperature 0
└──────┬──────┘
       ▼
┌─────────────┐  enforce: ≤3 sentences · exactly 1 link · dated footer
│  formatter  │
└──────┬──────┘
       ▼
    answer
```

| File | Responsibility |
|---|---|
| `src/ingest.py` | Fetch, parse `__NEXT_DATA__`, clean, chunk, embed, store in ChromaDB |
| `src/guardrails.py` | PII / advice / performance checks, run *before* retrieval |
| `src/retriever.py` | Question embedding + filtered ChromaDB query |
| `src/generator.py` | Groq call and the pipeline that chains all four stages |
| `src/formatter.py` | Enforces the answer contract |
| `app.py` | Streamlit UI (no logic of its own) |

---

## The corpus

Six public pages, all Groww:

| Scheme | Category |
|---|---|
| HDFC Large Cap Fund - Direct Growth | Large Cap |
| HDFC Flexi Cap Fund - Direct Growth | Flexi Cap |
| HDFC ELSS Tax Saver Fund - Direct Growth | ELSS |
| HDFC Small Cap Fund - Direct Growth | Small Cap |
| HDFC Balanced Advantage Fund - Direct Growth | Balanced Advantage |
| *Groww guide: downloading a capital gains statement* | how-to |

Defined in `data/sources.csv`, producing **46 chunks** embedded as 384-dim vectors
in `chroma_db/`.

### Two deliberate exclusions

**Returns and performance are stripped at ingestion.** Fields like `stats`,
`holdings` and `peerComparison` are dropped before chunking, so the model cannot
quote or compare them even if asked. Performance questions are refused and
redirected to the AMC's official factsheet.

**Personal data is never accepted.** PAN, Aadhaar, email, phone, OTP and
account/folio numbers are detected and the message is discarded before it reaches
the vector store or the LLM. Only the *category* is retained, never the value.

---

## Design decisions worth defending

**Scheme disambiguation uses metadata, not vector similarity.** MiniLM cannot
distinguish "HDFC Large Cap" from "HDFC Small Cap" — a question about Large Cap's
expense ratio returned the *Small Cap* chunk. A shortened-alias variant was
tested and scored identically, proving the cause is the model's semantics, not the
chunk text. The fix is deterministic: match the question against scheme aliases,
then pass an exact `where` filter to ChromaDB. Result:

| Metric | Pure vector search | With scheme filter |
|---|---|---|
| Correct scheme | 9/13 | **13/13** |
| Correct section within top-5 | 13/13 | **13/13** |

**Chunking is section-per-chunk with zero overlap.** The source data is already
atomic `label: value` pairs, so no fact spans a boundary and overlap would only
create duplicate retrieval candidates. A hard 900-character cap keeps every chunk
inside MiniLM's 256-token window, preventing silent truncation. Details in
`docs/chunking_strategy.md`.

**The formatter guarantees what the prompt only requests.** A prompt instruction
is a request; a formatter is a guarantee. The model can be talked into a fourth
sentence, but it cannot make the formatter emit two links — model-written URLs are
stripped and replaced with one canonical citation.

**Guardrails were tuned in both directions.** A guardrail that blocks valid
questions is worse than one that misses, so false positives were measured as
carefully as true positives: **0 blocked out of 100** legitimate fact questions,
against 22/22 advice and performance questions caught.

---

## Verification

Reproduce with `python src/generate_samples.py`; full transcript in
`samples/sample_qa.md`, generated from real pipeline output.

| Check | Result |
|---|---|
| Factual answers matching the verified corpus value | 12/12 |
| Guardrail refusals correct | 6/6 |
| Advice / performance questions caught | 22/22 |
| Correct scheme (metadata filter) | 13/13 |
| Correct section within top-5 | 13/13 |
| Guardrail false positives | 0/100 |
| PII values echoed back to the user | 0 |
| Answers exceeding 3 sentences | 0 |
| Answers with other than exactly 1 citation | 0 |
| Out-of-scope schemes answered honestly | 3/3 |
| UI flows (Streamlit `AppTest`, exceptions) | 5/5 |

Spot-checked corpus values: Large Cap 1.04%, Flexi Cap 0.77%, ELSS 1.21% /
Rs 500 / 3-year lock-in, Small Cap 0.79%, Balanced Advantage 0.78%. All five
schemes carry a "Moderately High" riskometer rating.

---

## Known limitations

**The corpus is entirely Groww, not official AMC/SEBI/AMFI sources.** Groww is a
third-party investment platform. The official site, `hdfcfund.com`, was the
intended primary source but hard-blocks automated requests with HTTP 403
(Akamai) — verified across multiple URLs, several header combinations, and a
separate server-side fetcher. Using Groww's own guide article as a sixth source
was the agreed substitute. For a production system, the factsheet PDFs on the AMC
site should be the source of record.

**Scheme names differ from the source pages.** The ingested payload calls two
schemes "HDFC Flexi Cap Direct Plan Growth" and "HDFC ELSS Tax Saver Fund Direct
Plan Growth", while `data/sources.csv` uses the Groww display names. Aliases in
`guardrails.SCHEME_ALIASES` bridge this, but it is a known rough edge.

**MiniLM is a small embedding model.** Section-level ranking within a scheme is
noisy — the top hit for a Large Cap expense-ratio question is often the `tax`
chunk, with the correct `fees` chunk at rank 2. The model reliably finds it
inside top-5, which is why top-k stays at 5 rather than 1.

**`temperature=0` makes answers reproducible but not insightful.** Fine for a
demo; a real deployment would want a little variety.

**The `GROQ_API_KEY` in `.env` is a live credential.** It is gitignored, never
logged, never printed, and never included in an error message — but if you share
this repository, rotate the key.

---

## Environment

- Python 3.10.5 · Streamlit 1.64.0 · ChromaDB 1.5.9 · sentence-transformers (all-MiniLM-L6-v2)
- Model: `openai/gpt-oss-120b` via Groq, temperature 0 (override with `GROQ_MODEL`)

The model default was chosen by listing what the API key can actually reach
rather than assuming. `llama-3.3-70b-versatile` — the model most tutorials use —
is not served on this account, so a hardcoded guess would have failed on the
first live call.
