# Architecture: Mutual Fund FAQ Assistant (Facts-Only RAG Chatbot)

**Based on:** `PRD.md`

A RAG chatbot that answers factual questions about 5 HDFC schemes using only the ingested source pages. Each answer is ≤3 sentences with one citation link and a "Last updated from sources" line. No advice.

---

## 1. Components

| Component | Responsibility |
|-----------|----------------|
| **Loader** | Fetches the 5 source URLs (`data/sources.csv`) and extracts clean text. |
| **Chunker** | Splits text into small, fact-preserving chunks and attaches metadata (`scheme_name`, `category`, `source_url`, `section`, `last_updated`). Also writes all chunks to `data/chunks.txt` for inspection. |
| **Embedder** | `all-MiniLM-L6-v2` (local, 384-dim). The same model embeds both chunks and user questions. |
| **Vector Store** | ChromaDB persisted to disk. Ingestion runs once, not on every restart. |
| **Retriever** | Embeds the question and fetches the top-k chunks, optionally filtered by scheme. |
| **Guardrails** | Before retrieval, refuses advice/opinion questions (with an educational link), declines return comparisons (points to the factsheet) and blocks PII (PAN, Aadhaar, phone, email, OTP). |
| **Generator** | Groq LLM answers from the retrieved context only. API key is read from `.env`. |
| **Formatter** | Enforces ≤3 sentences, appends one source link and the last-updated line. |
| **UI** | Welcome line, 3 example questions and the note "Facts-only. No investment advice." |

## 2. Data Flow

```
ingest → chunk → embed → store → retrieve → generate
```

1. **Ingest:** load the 5 HDFC scheme pages and clean the text.
2. **Chunk:** split into chunks, attach metadata and save to `chunks.txt`.
3. **Embed:** convert each chunk to a 384-dim vector with MiniLM.
4. **Store:** persist vectors, text and metadata in ChromaDB (one-time).
5. **Retrieve:** embed the user question with the same model and pull the top-k similar chunks.
6. **Generate:** Groq produces a short answer from those chunks, and the formatter adds the citation and date.

## 3. Tech Stack

| Layer | Choice |
|-------|--------|
| Language | Python |
| Embeddings | `sentence-transformers/all-MiniLM-L6-v2` (local, no API key) |
| Vector DB | ChromaDB (persistent, on disk) |
| LLM | Groq (key in `.env`, never committed) |
| Scraping | requests + BeautifulSoup |
| UI | Streamlit |

## 4. Folder Structure

```
mf-faq-rag/
├── .env                  # GROQ_API_KEY (git-ignored)
├── .env.example
├── .gitignore
├── README.md
├── requirements.txt
├── app.py                # UI
├── data/
│   ├── sources.csv       # the 5 URLs
│   └── chunks.txt        # readable chunks + metadata
├── chroma_db/            # persisted vector store
├── src/
│   ├── ingest.py         # load → chunk → embed → store
│   ├── guardrails.py
│   ├── retriever.py
│   ├── generator.py      # Groq call
│   └── formatter.py
└── samples/
    └── sample_qa.md      # 5-10 queries with answers + links
```

## 5. Query Flow (Text Diagram)

```
User question
     │
     ▼
[Guardrails] ── advice / PII / returns? ──► Polite refusal + link
     │ (factual)
     ▼
[Embed question]  (MiniLM)
     │
     ▼
[ChromaDB top-k search]
     │
     ▼
[Groq LLM]  (answer from retrieved chunks only)
     │
     ▼
[Formatter]  ≤3 sentences + 1 source link + "Last updated from sources: <date>"
     │
     ▼
UI answer
```
