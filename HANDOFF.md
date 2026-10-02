# HANDOFF — HDFC Mutual Fund Facts Bot

**Status: all 6 phases complete and verified.** Written so the project can be
picked up cold by another account or session.

Last updated: 2026-10-02

---

## 1. What this is

A facts-only RAG chatbot for a class demo. Answers questions about 5 HDFC mutual
fund schemes using **only** an ingested corpus of 6 public Groww pages. No
training data, no third-party blogs, no invented facts, no PII.

Every answer: **≤3 sentences**, **exactly one citation link**, ends with
`Last updated from sources: <date>`.

---

## 2. Resume in 60 seconds

```bash
cd "C:\Users\vedan\Desktop\milestone 4 building"
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Ingestion is already done and is idempotent — do **not** re-run it unless you
change `data/sources.csv`. If you must:

```bash
.\.venv\Scripts\python.exe src\ingest.py --rebuild
```

The API key is already in `.env` (gitignored). **If you are a different account,
you need your own key** from https://console.groq.com/keys — overwrite
`GROQ_API_KEY` in `.env`. Keep the same variable name; never paste a key into
source, docs or a commit.

---

## 3. Architecture decisions, and WHY

These are the decisions a newcomer is most likely to undo by accident. Each was
made from a measurement, not a preference.

### Loader parses `__NEXT_DATA__`, not rendered text

Groww pages are Next.js apps. Their rendered text is one blob mixed with nav bars
and a fund-comparator widget. The embedded `__NEXT_DATA__` JSON has exact labelled
fields (`exit_load`, `expense_ratio`, `minimum_investment`, …), which is why the
corpus is clean `label: value` data rather than prose.

### Performance data excluded at ingestion

Fields `stats`, `holdings` and `peerComparison` are dropped **before** chunking.
This is a hard guarantee: the LLM cannot quote or compare returns because those
numbers do not exist anywhere in the vector store. Cheaper and more reliable than
prompting the model not to use them.

### Chunking: section-per-chunk, overlap 0, hard 900-char cap

- Data is already atomic, so no fact spans a boundary and overlap only creates
  duplicate retrieval candidates.
- 900 chars keeps every chunk inside MiniLM's 256-token window. Without the cap,
  one CAMS chunk hit 1,986 chars and was silently truncated by the embedder.
- Rationale and numbers: `docs/chunking_strategy.md`.

### Scheme disambiguation uses metadata filtering, NOT the vector score

The single most important finding of this project.

MiniLM **cannot distinguish "HDFC Large Cap" from "HDFC Small Cap"** — a question
about Large Cap's expense ratio returned the Small Cap fees chunk. A
shortened-alias variant was tested on the theory that the repeated scheme name was
drowning the fact words; it scored identically (11/16, same failures), which
proved the cause is the model's semantics, not the chunk text.

The fix is deterministic: `guardrails.detect_scheme()` matches the question
against alias lists, then `retriever.retrieve()` passes an exact
`where={"scheme_name": ...}` filter to ChromaDB.

| Metric | Pure vector search | With scheme filter |
|---|---|---|
| Correct scheme | 9/13 | **13/13** |
| Correct section at rank 1 | 7/13 | 10/13 |
| Correct section within top-5 | 13/13 | **13/13** |

Right section at rank 1 is still noisy, but the right chunk is **always** inside
top-5 — which is what the LLM actually reads. That is why top-k stays at 5
instead of being pushed to 1 or raised.

### The embedded text has three prefix lines, each earned

```
Scheme: HDFC Small Cap Fund - Direct Growth (Small Cap)
Facts: expense ratio, base expense ratio, exit load, stamp duty
Section: fees
Expense ratio of HDFC Small Cap Fund Direct Growth: 0.79%
```

| Variant | Correct scheme + section at rank 1 |
|---|---|
| Body only, no prefix | 3/4 — but returned the **wrong scheme** |
| `Scheme:` + `Section:` + body | 5/6 |
| `Scheme:` + **`Facts:`** + `Section:` + body | **6/6** |

`Scheme:` is load-bearing (without it, Flexi Cap answers a Small Cap question).
`Facts:` matters because the body buries the field name.

### The formatter guarantees what the prompt only requests

A prompt instruction is a request; a formatter is a guarantee. The model can be
talked into a fourth sentence, but it cannot make `formatter.py` emit two links —
model-written URLs are stripped and replaced with one canonical citation. Sentence
splitting uses `(?<=[.!?])\s+` so `1.04%` and `Rs 1,405.49` are never split.

### Guardrails run BEFORE retrieval

A blocked question must never reach ChromaDB or Groq. Verified: blocked questions
retrieve **0 chunks**.

### temperature=0

Answers are reproducible, so a live demo won't surprise you mid-presentation.

---

## 4. Gotchas that cost time — do not reintroduce

| Gotcha | Fix |
|---|---|
| `requests` defaults to ISO-8859-1; `resp.text` mangled smart quotes into U+FFFD | decode `resp.content` as UTF-8 |
| `Path.write_text` translates `\n`→`\r\n` on Windows | normalise line endings before regex matching |
| Page boilerplate ("You may also want to know", "Disclaimer:", "Check More AMCs") leaked into chunks | `strip_boilerplate()` |
| Chunking silently produced 0 chunks | `[0]` vs `[1]` split-index bug, fixed |
| `fund_manager` field is stale on these pages (said "Prashant Jain" for Large Cap while the page showed Rahul Baijal/Dhruv Muchhal) | read managers from `fund_manager_details[].person_name` |
| Splitting needed 3 fallback boundaries in order: `Step \d+:`, sentence end, line break | `fees` sections have no sentence punctuation, so line break (whole `label: value` pairs) was required |
| `llama-3.3-70b-versatile` — the model nearly every tutorial uses — is **not served** on this account | default set to `openai/gpt-oss-120b` after listing the account's real models |
| Blocking a question leaves `in_sources=True` by default | `generator.answer_question()` explicitly sets `in_sources=False` on the blocked path |
| Console emoji crash (`cp1252` can't encode 🔒/🚫) | `sys.stdout.reconfigure(encoding="utf-8")` in any script printing app status text |

---

## 5. Verified corpus facts

Cross-checked against `data/raw/*.txt`. If an answer ever disagrees with this
table, **the answer is wrong**, not the table.

| Scheme | Expense ratio | Exit load | Min SIP | Benchmark | Riskometer |
|---|---|---|---|---|---|
| Large Cap | 1.04% | 1% if <1yr | Rs 100 | NIFTY 100 TRI | Moderately High |
| Flexi Cap | 0.77% | 1% if <1yr | Rs 100 | NIFTY 500 TRI | Moderately High |
| ELSS Tax Saver | 1.21% | Nil | Rs 500 | NIFTY 500 TRI | Moderately High |
| Small Cap | 0.79% | 1% if <1yr | Rs 100 | BSE 250 SmallCap TRI | Moderately High |
| Balanced Advantage | 0.78% | 1% on excess >15% within 1yr | Rs 100 | NIFTY 50 Hybrid 50:50 | Moderately High |

ELSS lock-in: **3 years**.

⚠️ Two scheme names in the chunk text differ from `data/sources.csv` because they
come from the page payload: "HDFC Flexi Cap Direct Plan Growth" and
"HDFC ELSS Tax Saver Fund Direct Plan Growth". `SCHEME_ALIASES` bridges this.

---

## 6. File map

```
.env                      GROQ_API_KEY  (gitignored — the ONLY place the key lives)
.env.example              template, keep empty
README.md                 user-facing docs
app.py                    Streamlit UI — no logic of its own
requirements.txt
data/
  sources.csv             6 rows: source_type, scheme_name, category, url
  raw/*.txt               6 cleaned sources (regenerable via --rebuild)
  chunks.txt              all 46 chunks, human-readable dump
chroma_db/                persisted vectors + manifest.json (gitignored)
docs/
  prd.md                  FR1–FR8, acceptance criteria, test queries
  implementation.md       the 6-phase plan
  architecture.md         components, folder structure, query flow
  chunking_strategy.md    chunk design + Phase 3 retrieval findings (§7)
  problemStatement.txt    original brief
samples/
  sample_qa.md            verified outputs, regenerated from real runs
  ui_test.py              headless Streamlit AppTest of app.py
src/
  ingest.py               fetch → parse → clean → chunk → embed → store
  guardrails.py           PII / advice / performance + detect_scheme()
  retriever.py            embed question + filtered ChromaDB query
  generator.py            Groq call + the pipeline chaining all stages
  formatter.py            answer contract enforcement
  generate_samples.py     regenerates sample_qa.md
```

**Module coupling to respect:** `retriever.py` imports `detect_scheme` from
`guardrails.py` **on purpose**. If they use different alias logic, the guardrail
and the retriever can disagree about which scheme the user meant — a subtle,
hard-to-debug bug. Do not "clean this up" by duplicating the aliases.

---

## 7. Verification (all currently passing)

| Check | Result |
|---|---|
| Factual answers matching the verified value | 12/12 |
| Guardrail refusals correct | 6/6 |
| Advice / performance caught | 22/22 |
| Correct scheme (metadata filter) | 13/13 |
| Correct section within top-5 | 13/13 |
| Guardrail false positives | 0/100 legitimate questions |
| PII values echoed back | 0 |
| Answers exceeding 3 sentences | 0 |
| Answers with other than exactly 1 citation | 0 |
| Out-of-scope schemes answered honestly | 3/3 |
| UI flows (AppTest, zero exceptions) | 5/5 |
| Real API key outside `.env` | 0 occurrences |

Reproduce: `python src/generate_samples.py` and `python samples/ui_test.py`.

---

## 8. Known limitations — state these, don't hide them

1. **The corpus is entirely Groww, a third-party platform — not official
   AMC/SEBI/AMFI sources.** `hdfcfund.com` was the intended primary source but
   hard-blocks automation with HTTP 403 (Akamai). Verified across 3 URLs, several
   header sets, and a separate server-side fetcher. Groww's own guide article was
   the agreed substitute for source 6. For production, the AMC's official
   factsheet PDFs should be the source of record.
2. **Section ranking within a scheme is noisy.** Top hit for a Large Cap
   expense-ratio question is often the `tax` chunk, with the correct `fees` chunk
   at rank 2. Harmless at top-k=5; would matter if you cut k to 1.
3. **Two scheme names don't match `sources.csv`** (see §5).
4. **No conversation memory.** Each question is independent.
5. **English only**, single-turn, no follow-up resolution ("what about its exit
   load?" won't resolve "its").

---

## 9. If you need to extend this

- **Add a scheme:** append a row to `data/sources.csv`, add its aliases to
  `SCHEME_ALIASES`, then `python src/ingest.py --rebuild`. The manifest
  signature will detect the corpus change and force a re-embed automatically.
- **Switch model:** set `GROQ_MODEL` in `.env`. No code change. List what your
  key can actually reach via `client.models.list()` before choosing.
- **Tune retrieval:** `TOP_K` and `WEAK_MATCH_THRESHOLD` in `retriever.py`.
  Good matches measure 0.17–0.41 cosine distance; the weak threshold is 0.60.
- **Add a guardrail:** a new check in `guardrails.check()`, respecting the
  priority order PII > advice > performance > pass. Re-measure false positives —
  that 0/100 number is the thing most likely to regress silently.
