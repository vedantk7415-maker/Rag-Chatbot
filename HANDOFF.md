# HANDOFF — HDFC Mutual Fund Facts Bot

**Status: all 6 phases built and verified. Local app fully working.
Memory blocker RESOLVED — fits the 512 MB budget with 277 MB headroom (see §4).**
Awaiting Render redeploy.

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

Ingestion is done and idempotent — do **not** re-run it unless
`data/sources.csv` changes.

A different account needs its own key: `GROQ_API_KEY` in `.env`.
Keep the variable name; never put a key in source, docs or a commit.

---

## 3. Current git state

| | |
|---|---|
| Remote | `https://github.com/vedantk7415-maker/Rag-Chatbot` |
| Branch | `main` |
| Commits | `c66b137` (Render blueprint) ← `a9b5bfe` (initial build) |
| Pushed | yes, in sync |
| `.env` tracked | **no** — verified ignored |

If you change code, commit and push again before redeploying; Render deploys
from the remote, not from disk.

---

## 4. The memory blocker — RESOLVED

Render's free tier caps memory at **512 MB**. The app was killed on startup with
`Ran out of memory (used over 512MB)`.

Measured, not guessed:

| Configuration | Peak |
|---|---|
| chromadb + baseline | 67 MB |
| + embedding model loaded (PyTorch) | 528 MB |
| + embedding 46 chunks | 631 MB |
| + Streamlit, real app.py, 3 live questions | **~700 MB** |

**Root cause: PyTorch's runtime is 455 MB on its own** — a single library import,
not our data. 46 chunks of text is kilobytes.

### The fix

`src/embedder.py` embeds with ONNX Runtime plus the Rust `tokenizers` library,
bypassing `sentence-transformers` and `transformers` entirely. `ingest.get_model()`
returns this instead. Neither torch nor transformers is imported anywhere at
runtime.

`all-MiniLM-L6-v2` uses attention-masked mean pooling then L2 normalisation
(confirmed from `1_Pooling/config.json` and `modules.json`); the module
reproduces that pipeline exactly.

### The second bug: ingestion batch size (this is what actually got OOM-killed)

Swapping PyTorch for ONNX fixed the *query* path (539 -> 208 MB), but the app
still died. The reason: the start command runs `ingest.py` and `streamlit run` as
**two separate processes**, and only the query path had been measured.

MiniLM's attention scores are `batch x 12 heads x 256 seq x 256 seq` float32 =
~48 MB **per layer**, so ~288 MB across 6 layers at `batch_size=16`. Measured
peak while embedding the same 46 chunks:

| batch_size | peak | delta over baseline | theory |
|---|---|---|---|
| 16 | 451 MB | +278 MB | 288 MB |
| 8 | — | — | 144 MB |
| 4 | **247 MB** | **+69 MB** | 72 MB |
| 1 | 198 MB | +18 MB | 18 MB |

Theory and measurement agree within ~4%, so this is the whole story.
`batch_size=16` took ingestion to **489 MB** against a 512 MB budget. Default is
now **4** (`DEFAULT_BATCH_SIZE` in `embedder.py`).

Because ingest and streamlit are separate processes, the container peak is
`max(ingest, streamlit)`, not their sum.

### The third bug: Streamlit's file watcher (the one actually being killed)

Even after both fixes above, Render still returned `Out of memory (used over
512Mi)` — and Streamlit's own `==>` prefix proved it was the **start** phase,
immediately after the HF model download.

Measured locally, though, nothing came close:

| Stage | Peak |
|---|---|
| `Embedder()` cold construction | 168 MB |
| `ingest.py`, fresh store | 283 MB |
| `app.py`, 3 live questions | 235 MB |

So the code fit in 512 MB locally and not in the cloud. The difference is
**Streamlit's file watcher**: it walks the entire working directory to enable hot
reload, and on Render that directory also holds a freshly `pip install`ed `.venv`
with thousands of files. That cost does not exist in a local run, which is
exactly why local measurement could not reproduce it.

Fixed in `.streamlit/config.toml` via `fileWatcherType = "none"`. Hot reload is a
development convenience and worthless in production.

Two supporting changes:

- **`chroma_db/` is committed and ingestion removed from the start command.**
  The OOM appeared right at the ~90 MB model download, which happened *only*
  because ingest ran at boot. Shipping the store removes that download, removes
  an entire second process from the container, and stops the deploy depending on
  Groww being reachable from Render's IP. Cold start: 3–5 min → ~30 s.
- The same warning line made the phase unambiguous, which is the one genuinely
  useful thing about it. **When a deploy fails, read which phase printed the
  error before changing code.**

### Results

| Measurement | Before | After |
|---|---|---|
| `ingest.py`, fresh store | 489 MB | 283 MB (no longer run at boot) |
| Query path | 539 MB | 208 MB |
| Real `app.py`, 3 live questions | ~700 MB | **235 MB** |
| Headroom vs 512 MB | −190 MB | **+277 MB** |

Parity with the original `sentence-transformers` embedder over all 46 real corpus
chunks: **minimum cosine 0.99999982**, max absolute difference **1.75e-07**
(float32 noise). Retrieval scores identical: 13/13 scheme, 10/13 rank-1, 13/13
top-5.

### Things that were tried and rejected — do not retry

| Attempt | Result |
|---|---|
| Thread caps (`OMP_NUM_THREADS=1`, `torch.set_num_threads(1)`) | saves 12 MB. Useless. |
| `SentenceTransformer(..., backend="onnx")` + `optimum` | **Worse — 701 MB.** `transformers` imports torch even when ONNX is requested, so both runtimes load. |

### Verify it yourself

```bash
python samples/regression.py    # 9/9 checks + peak memory
python samples/measure_app.py   # real app.py, 3 questions
python -c "import sys; sys.path.insert(0,'src'); import embedder, ingest; print(embedder.verify_parity([c.text for c in ingest.make_chunks()]))"
```

---

## 5. Dependency incident — do not repeat

Installing `optimum[onnxruntime]` silently **downgraded** `transformers` to
4.57.6 and `huggingface-hub` to 0.36.2, breaking sentence-transformers 6.1.0
(requires `transformers>=5.0.0,<6.0.0` and `huggingface-hub>=1.3.0,<2.0.0`).

Restored by:
```bash
pip uninstall -y optimum
pip install "transformers>=5.0.0,<6.0.0" "huggingface-hub>=1.3.0,<2.0.0"
```

**Current healthy state (verified):** transformers 5.18.0, sentence-transformers
6.1.0, huggingface-hub 1.33.0, streamlit 1.64.0, chromadb 1.5.9.

`optimum` is still installed and now unused — safe to remove.

Lesson: `pip install` a single package in a working project can quietly break it.
Check versions after any install, not before.

---

## 6. Architecture decisions, and WHY

Each was made from a measurement, not a preference.

### Loader parses `__NEXT_DATA__`, not rendered text

Groww pages are Next.js apps. Rendered text is one blob mixed with nav and a
fund-comparator widget. The embedded `__NEXT_DATA__` JSON has exact labelled
fields (`exit_load`, `expense_ratio`, `minimum_investment`), which is why the
corpus is clean `label: value` data.

### Performance data excluded at ingestion

Fields `stats`, `holdings` and `peerComparison` are dropped **before** chunking.
The LLM cannot quote or compare returns because those numbers do not exist in the
vector store. Cheaper and more reliable than prompting the model not to use them.

### Chunking: section-per-chunk, overlap 0, hard 900-char cap

Data is already atomic, so no fact spans a boundary and overlap only creates
duplicate retrieval candidates. The 900-char cap keeps every chunk inside
MiniLM's 256-token window — without it one CAMS chunk hit 1,986 chars and was
silently truncated by the embedder. Detail in `docs/chunking_strategy.md`.

### Scheme disambiguation uses metadata filtering, NOT the vector score

The most important finding in the project.

MiniLM **cannot distinguish "HDFC Large Cap" from "HDFC Small Cap"** — a question
about Large Cap's expense ratio returned the Small Cap fees chunk. A
shortened-alias variant was tested on the theory that the repeated scheme name was
drowning the fact words; it scored identically (11/16, same failures), proving the
cause is the model's semantics, not the chunk text.

Fix: `guardrails.detect_scheme()` matches aliases, then `retriever.retrieve()`
passes an exact `where={"scheme_name": ...}` filter to ChromaDB.

| Metric | Pure vector search | With scheme filter |
|---|---|---|
| Correct scheme | 9/13 | **13/13** |
| Correct section at rank 1 | 7/13 | 10/13 |
| Correct section within top-5 | 13/13 | **13/13** |

Right section at rank 1 stays noisy, but the right chunk is **always** in top-5 —
which is what the LLM reads. That is why top-k stays at 5.

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
talked into a fourth sentence, but cannot make `formatter.py` emit two links.
Sentence splitting uses `(?<=[.!?])\s+` so `1.04%` and `Rs 1,405.49` never split.

### Guardrails run BEFORE retrieval

A blocked question must never reach ChromaDB or Groq. Verified: blocked questions
retrieve **0 chunks**.

### temperature=0

Reproducible answers, so a live demo won't surprise you mid-presentation.

---

## 7. Gotchas that cost time — do not reintroduce

| Gotcha | Fix |
|---|---|
| `requests` defaults to ISO-8859-1; `resp.text` mangled smart quotes into U+FFFD | decode `resp.content` as UTF-8 |
| `Path.write_text` translates `\n`→`\r\n` on Windows | normalise line endings before regex matching; `.gitattributes` pins LF in the repo |
| Page boilerplate ("You may also want to know", "Disclaimer:", "Check More AMCs") leaked into chunks | `strip_boilerplate()` |
| Chunking silently produced 0 chunks | `[0]` vs `[1]` split-index bug |
| `fund_manager` is stale on these pages (said "Prashant Jain" for Large Cap while the page showed Rahul Baijal/Dhruv Muchhal) | read from `fund_manager_details[].person_name` |
| Splitting needed 3 fallbacks in order: `Step \d+:`, sentence end, line break | `fees` sections have no sentence punctuation, so line break was required |
| `llama-3.3-70b-versatile` — what most tutorials use — is **not served** on this account | default is `openai/gpt-oss-120b`, chosen by listing the account's real models |
| Blocked questions left `in_sources=True` by default | `generator.answer_question()` sets `in_sources=False` on the blocked path |
| Console emoji crash (cp1252 can't encode 🔒/🚫) | `sys.stdout.reconfigure(encoding="utf-8")` |
| `pip install optimum` broke transformers/hub | see §5 |
| Only 11 models on the Groq key, mostly speech and guard models | always list before hardcoding a model name |

---

## 8. Verified corpus facts

Cross-checked against `data/raw/*.txt`. If an answer disagrees with this table,
**the answer is wrong**, not the table.

| Scheme | Expense ratio | Exit load | Min SIP | Benchmark | Riskometer |
|---|---|---|---|---|---|
| Large Cap | 1.04% | 1% if <1yr | Rs 100 | NIFTY 100 TRI | Moderately High |
| Flexi Cap | 0.77% | 1% if <1yr | Rs 100 | NIFTY 500 TRI | Moderately High |
| ELSS Tax Saver | 1.21% | Nil | Rs 500 | NIFTY 500 TRI | Moderately High |
| Small Cap | 0.79% | 1% if <1yr | Rs 100 | BSE 250 SmallCap TRI | Moderately High |
| Balanced Advantage | 0.78% | 1% on excess >15% within 1yr | Rs 100 | NIFTY 50 Hybrid 50:50 | Moderately High |

ELSS lock-in: **3 years**.

⚠️ Two scheme names in chunk text differ from `data/sources.csv` because they
come from the page payload: "HDFC Flexi Cap Direct Plan Growth" and "HDFC ELSS
Tax Saver Fund Direct Plan Growth". `SCHEME_ALIASES` bridges this.

---

## 9. File map

```
.env                      GROQ_API_KEY  (gitignored — the ONLY place the key lives)
.env.example              template, keep empty
.gitattributes            pins LF; this project already hit a CRLF bug
.gitignore                .env, chroma_db/, .venv/, __pycache__/
render.yaml               Render blueprint; GROQ_API_KEY uses sync:false
README.md                 user-facing docs
HANDOFF.md                this file
app.py                    Streamlit UI — no logic of its own
requirements.txt
data/
  sources.csv             6 rows: source_type, scheme_name, category, url
  raw/*.txt               6 cleaned sources (regenerable via --rebuild)
  chunks.txt              all 46 chunks, human-readable dump
chroma_db/                persisted vectors + manifest.json (gitignored)
docs/                     prd, implementation, architecture, chunking_strategy, brief
samples/
  sample_qa.md            verified outputs, regenerated from real runs
  ui_test.py              headless Streamlit AppTest of app.py
  measure_memory.py       RSS breakdown of the query path
  measure_backends.py     torch vs onnx backend comparison
src/
  ingest.py               fetch → parse → clean → chunk → embed → store
  guardrails.py           PII / advice / performance + detect_scheme()
  retriever.py            embed question + filtered ChromaDB query
  generator.py            Groq call + the pipeline chaining all stages
  formatter.py            answer contract enforcement
  generate_samples.py     regenerates sample_qa.md
  embedder.py             (in progress) lightweight ONNX embedder, no torch
```

**Module coupling to respect:** `retriever.py` imports `detect_scheme` from
`guardrails.py` **on purpose**. If they use different alias logic, the guardrail
and the retriever can disagree about which scheme the user meant — subtle and
hard to debug. Do not "clean this up" by duplicating the aliases.

---

## 10. Verification (all currently passing, pre-Option-A)

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

Reproduce: `python src/generate_samples.py`, `python samples/ui_test.py`.

**After the embedder change, every row above must be re-run.** Parity check
(cosine similarity between old and new vectors) must exceed 0.999.

---

## 11. Known limitations — state these, don't hide them

1. **The corpus is entirely Groww, a third-party platform — not official
   AMC/SEBI/AMFI sources.** `hdfcfund.com` was the intended primary source but
   hard-blocks automation with HTTP 403 (Akamai), verified across 3 URLs,
   several header sets and a separate server-side fetcher. Groww's own guide
   article was the agreed substitute for source 6. For production, the AMC's
   official factsheet PDFs should be the source of record.
2. **Section ranking within a scheme is noisy.** Top hit for a Large Cap
   expense-ratio question is often the `tax` chunk, with the correct `fees` chunk
   at rank 2. Harmless at top-k=5; would matter if k were cut to 1.
3. **Two scheme names don't match `sources.csv`** (see §8).
4. **No conversation memory.** Single-turn only; "what about its exit load?"
   won't resolve "its".
5. **English only.**
6. **`temperature=0` answers are reproducible but not insightful.** Fine for a
   demo; a real deployment would want a little variety.
7. **`GROQ_API_KEY` is a live credential** in `.env`. Gitignored, never logged,
   never printed, never in an error message. Rotate if you share this repo.

---

## 12. Deployment settings

| Field | Value |
|---|---|
| Repo | `https://github.com/vedantk7415-maker/Rag-Chatbot` |
| Root Directory | blank |
| Build Command | `pip install --upgrade pip && pip install -r requirements.txt` |
| Start Command | `streamlit run app.py --server.port $PORT --server.address 0.0.0.0 --server.headless true --server.fileWatcherType none --browser.gatherUsageStats false` |
| Env | `GROQ_API_KEY` (secret), `PYTHON_VERSION=3.11.9` |

**`chroma_db/` is now committed** and ingestion is **not** part of the start
command. Cold start is roughly 30 seconds instead of 3–5 minutes, and the deploy
no longer depends on Groww being reachable from Render's datacenter IP.

If you change the corpus, rebuild the store or the deployment serves stale
vectors:

```bash
python src/ingest.py --rebuild
git add -A && git commit -m "rebuild vector store"
```

`.streamlit/config.toml` ships with the repo and sets `fileWatcherType = "none"`
plus `headless = true`, so the dashboard's start command does not need the
redundant flags. CORS and XSRF protection are deliberately left at Streamlit's
secure defaults — do not disable them, the app is publicly reachable.

---

## 13. If you need to extend this

- **Add a scheme:** append to `data/sources.csv`, add aliases to
  `SCHEME_ALIASES`, then `python src/ingest.py --rebuild`. The manifest signature
  detects the corpus change and forces a re-embed automatically.
- **Switch model:** set `GROQ_MODEL` in `.env`. List what the key can actually
  reach via `client.models.list()` before choosing.
- **Tune retrieval:** `TOP_K` and `WEAK_MATCH_THRESHOLD` in `retriever.py`.
  Good matches measure 0.17–0.41 cosine distance; weak threshold is 0.60.
- **Add a guardrail:** in `guardrails.check()`, respecting priority
  PII > advice > performance > pass. **Re-measure false positives** — that 0/100
  number is the thing most likely to regress silently.
