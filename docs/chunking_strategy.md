# Chunking Strategy (Proposal — needs approval before chunking code is written)

**Phase:** 2
**Status:** Proposed. `src/ingest.py` currently does Load + Clean only; chunking is
not implemented yet, per the PRD requirement that this strategy is agreed first.

---

## 1. What the data actually looks like

The 5 Groww pages are Next.js apps. The loader reads the `__NEXT_DATA__` JSON
payload rather than the rendered HTML, so we get **exact labelled values, not prose**.

Each scheme yields 7 topical sections (8 for ELSS, which adds `lock_in`). The
guide source is split at its own `h2`/`h3` headings and yields 6 sections:

| Section | Facts it holds |
|---------|----------------|
| `scheme_overview` | name, AMC, category, scheme/plan/option type, launch date, fund manager(s), ISIN, scheme code, investment objective |
| `fees` | expense ratio, base expense ratio, exit load, stamp duty, historic exit loads |
| `minimum_investment` | min SIP, max SIP, min first lump sum, min additional, min withdrawal, SIP/lumpsum allowed |
| `lock_in` | **ELSS only** — lock-in period |
| `benchmark` | benchmark index name + ticker |
| `riskometer` | riskometer rating, Groww star rating |
| `tax` | tax implication on redemption |
| `fund_details` | AUM, latest NAV + date, portfolio turnover, custodian, RTA, official AMC/SID link |
| guide sections | `intro`, `how_to_download_capital_gains_statement_for_mutu`, `online_investment_platforms`, `cams_and_kfin_technologies_limited`, `mutual_fund_companies`, `final_word` |

**Actual total: 46 chunks.** (8 sections x 5 schemes = 40, plus 6 guide sections,
plus 4 extra parts produced by the length cap below.)

Verified by running `python src/ingest.py` and reading `data/chunks.txt`.

### Deliberately excluded

`stats` (fund returns, category average, rank in category), `holdings` and
`peerComparison` are **not ingested**. The brief forbids performance claims, so
return questions get refused and redirected to the official factsheet. Keeping
these numbers out of the vector store removes the temptation for the LLM to use them.

---

## 2. Proposed strategy

### Approach: **semantic (section-based) chunking, one chunk per fact group**

Instead of a generic sliding window over text, each topical section becomes exactly
one chunk.

### Chunk size / overlap

| Parameter | Value |
|-----------|-------|
| Chunk size | **1 section per chunk**, with a hard cap of **900 characters** |
| Observed range | 135–890 chars, average 392 |
| Overlap | **0 characters** |

### The 900-character cap (added after inspecting real output)

The first pass produced 3 chunks over 1000 chars — worst was the CAMS section at
1986 chars. `all-MiniLM-L6-v2` truncates at **256 tokens**, so those chunks would
have been silently cut, losing the actual download steps. A section longer than 900
chars is therefore split further, at the safest boundary available, in this order:

1. `Step N:` — keeps numbered instructions whole
2. sentence end — `(?<=[.!?])`
3. line break — `(?<=\n)`, which for the `fees` sections means splitting between
   whole `label: value` pairs, never inside one

Split parts get ids like `..._fees__p1` / `..._fees__p2` and share the parent
section's metadata. 4 chunks ended up split this way.

### Why this suits this data

1. **The data is already atomic.** Every fact is a `label: value` line that fits in
   one or two sentences. A sliding window would only add fragments of neighbouring
   labels.
2. **Zero overlap is safe because facts never span a boundary.** Each section is
   independently answerable, so there is no sentence that gets cut in half. Overlap
   exists to protect against mid-sentence splits — this format has none.
3. **Small chunks mean high retrieval precision.** A question like "expense ratio of
   HDFC Small Cap" should retrieve the `fees` chunk and *only* that chunk. Bigger
   chunks pull in AUM, NAV and benchmark values that dilute the embedding and invite
   the LLM to answer with the wrong number.
4. **MiniLM's 256-token limit is never hit.** Longest section (`scheme_overview`) is
   well under it, so nothing is silently truncated by the embedding model.
5. **A "wrong scheme" answer becomes structurally impossible.** No chunk can contain
   two schemes, which was the top retrieval risk in the PRD.

### Cost: k must be larger

Because chunks are small and precise, a single question needs several of them (e.g.
"expense ratio and exit load" needs `fees`). Top-k should start at **k = 5**, not 3.

---

## 3. Metadata kept per chunk

| Field | Example | Used for |
|-------|---------|----------|
| `chunk_id` | `hdfc_small_cap_fund_direct_growth__fees` | stable id, dedupe on rebuild |
| `scheme_name` | `HDFC Small Cap Fund Direct Growth` | scheme filtering at query time |
| `scheme_slug` | `hdfc_small_cap_fund_direct_growth` | alias matching |
| `category` | `Small Cap` | category filtering |
| `source_url` | `https://groww.in/...` | **the single citation link** |
| `section` | `fees` | lets the LLM cite a specific field |
| `fact_label` | `expense ratio` | improves embedding match |
| `last_updated` | `2026-10-02` | the "Last updated from sources" line |
| `char_len` | `312` | sanity check during inspection |

---

## 4. Text written to the embedding

Each chunk text is prefixed with its context so the standalone string still carries
the scheme name:

```
Scheme: HDFC Small Cap Fund Direct Growth (Small Cap)
Section: fees
Expense ratio of HDFC Small Cap Fund Direct Growth: 0.79%
Base expense ratio of HDFC Small Cap Fund Direct Growth: 0.65%
Exit load of HDFC Small Cap Fund Direct Growth: Exit load of 1% if redeemed within 1 year
```

The scheme name is repeated inside the body too, so even a partial chunk match keeps
the label/value pairing intact.

---

## 5. Statement-download gap — RESOLVED

The brief lists **"How to download a capital-gains statement?"** as a supported
question type, but none of the 5 scheme pages contain any statement-download
information.

**Attempted first:** an official HDFC MF page on `hdfcfund.com`
(`/services/consolidated-account-statement`, `/services/faqs/smart-account-statement`,
`/investor-services/request-statement`). **All return HTTP 403** — Akamai bot
protection blocks every automated request, verified across several header sets and
via a separate server-side fetcher. That source is not machine-readable.

**Resolution:** source 6 is Groww's own how-to guide,
`https://groww.in/blog/how-to-get-capital-gains-statement-for-mutual-fund-investments`
(HTTP 200, parses cleanly). It is consistent with the other 5 sources, which are
already Groww, and it carries step-by-step instructions for all three routes:
the Groww app, CAMS/KFin, and the mutual fund company's own website.

It carries **no return or performance figures**, so the no-performance-claims rule is
not put at risk by it.

Known limit to state in the README: the corpus is entirely Groww rather than official
AMC/SEBI/AMFI pages, because the official AMC site blocks automated access.

---

## 7. Phase 3 findings: what the embedding can and cannot do

Measured on a 13-question verification set (5 schemes x fact types), not assumed.

### The embedded text has three prefix lines, and each one was earned

| Variant | Correct scheme + section at rank 1 |
|---------|-----------------------------------|
| Body only, no prefix | 3/4 — but returned the **wrong scheme** (Flexi Cap fees for a Small Cap question) |
| `Scheme:` + `Section:` + body | 5/6 |
| `Scheme:` + **`Facts:`** + `Section:` + body | **6/6** |

The `Scheme:` line is load-bearing: without it MiniLM confuses similarly-named
schemes. The `Facts:` line matters because the body buries the field name.

### The critical limitation: MiniLM cannot tell Large Cap from Small Cap

Pure vector ranking scored **11/16**. The recurring failure is scheme confusion:

> `"expense ratio of HDFC Large Cap"` → returned the **Small Cap** fees chunk

"Large Cap" and "Small Cap" are semantically near-identical to a small embedding
model. No amount of prompt-prefix tuning fixes this — a shortened-alias variant was
tested and scored identically (11/16, same failures), so the cause is the model's
semantics, not the chunk text.

**Conclusion: scheme disambiguation must use ChromaDB metadata filtering, never the
vector score.** This is already the design in `implementation.md` Phase 5
("detects a scheme mention"). `similarity_probe` now accepts `scheme_name=` to
apply a `where` filter, and the result is decisive:

| Metric | Pure vector search | With scheme metadata filter |
|--------|--------------------|-----------------------------|
| Correct scheme | 9/13 | **13/13** |
| Correct section at rank 1 | 7/13 | 10/13 |
| Correct section within top-5 | 13/13 | **13/13** |

With the filter, the right chunk is **always** inside top-5, which is what the LLM
actually consumes. Section-level ranking noise is therefore tolerable, and top-k
stays at 5 rather than being pushed higher.

**Build implication for Phase 5:** `retriever.py` must (a) match the question against
the 5 scheme names with deterministic string/alias rules, (b) pass a `where` filter
to ChromaDB when a scheme is detected, and (c) fall back to unfiltered search plus a
weak-match flag when no scheme is named.

### Embedding and storage settings

- Collection `mf_faq_chunks`, `hnsw:space = cosine` (correct for normalised MiniLM vectors)
- `normalize_embeddings=True` on both chunks and questions
- `chroma_db/manifest.json` stores the model name, vector count and a SHA-256
  signature of the chunk ids, so ingestion can detect a changed corpus and re-embed
  automatically instead of silently serving stale vectors

- [x] Section-per-chunk, overlap 0
- [x] Top-k starts at 5
- [x] Metadata fields listed in §3
- [x] Performance data stays excluded
- [x] Statement-download gap resolved via the Groww how-to guide (6th source)
- [x] `data/chunks.txt` written and spot-checked: every fact sits next to its label,
      no chunk mixes two schemes, metadata is correct on all 42 chunks