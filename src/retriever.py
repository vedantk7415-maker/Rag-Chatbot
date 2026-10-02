"""
Phase 5 (part 1): Retrieval.

Question -> embed with the same MiniLM -> top-k chunks from ChromaDB.

Scheme disambiguation uses an exact ChromaDB metadata filter, never the vector
score. Measured justification is in docs/chunking_strategy.md section 7: pure
embedding similarity confuses "HDFC Large Cap" with "HDFC Small Cap" (9/13 correct
scheme), while the metadata filter gives 13/13 and keeps the right chunk inside
top-5 every time.

The scheme aliases are imported from guardrails on purpose, so the guardrail and
the retriever can never disagree about which scheme the user meant.
"""

from __future__ import annotations

from dataclasses import dataclass

from guardrails import detect_scheme
from ingest import get_client, get_collection, get_model

TOP_K = 5

# Cosine distance. Good matches observed at 0.17-0.41; anything above this is
# treated as a weak match and answered with the "not in my sources" message
# instead of a guess. Tuned against the 13-question verification set.
WEAK_MATCH_THRESHOLD = 0.60


@dataclass
class RetrievedChunk:
    chunk_id: str
    scheme_name: str
    section: str
    source_url: str
    last_updated: str
    distance: float
    text: str

    def as_citation(self) -> dict:
        return {"source_url": self.source_url, "last_updated": self.last_updated}


def _to_chunk(raw_id: str, meta: dict, document: str, distance: float) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=raw_id,
        scheme_name=meta.get("scheme_name", ""),
        section=meta.get("section", ""),
        source_url=meta.get("source_url", ""),
        last_updated=meta.get("last_updated", ""),
        distance=round(float(distance), 4),
        text=document,
    )


def embed_question(question: str):
    """Same model, same normalisation as ingestion. One model, both sides."""
    return get_model().encode(
        [question], convert_to_numpy=True, normalize_embeddings=True
    )[0]


def retrieve(
    question: str,
    top_k: int = TOP_K,
    scheme_name: str | None = None,
    auto_detect: bool = True,
) -> tuple[list[RetrievedChunk], str | None, bool]:
    """
    Return (chunks, detected_scheme_name, is_weak_match).

    Filtering:
      - a scheme is named  -> exact `where` filter on metadata.scheme_name
      - no scheme named   -> unfiltered search across all 5 schemes
      - two schemes named -> detect_scheme returns None, so unfiltered, and the
                             LLM is told to answer only if one scheme fits
    """
    if auto_detect and scheme_name is None:
        scheme_name = detect_scheme(question)

    collection = get_collection(get_client(), create=False)
    if collection is None or collection.count() == 0:
        raise RuntimeError(
            "Vector store is empty. Run: python src/ingest.py  (ingestion is one-time)"
        )

    vector = embed_question(question).tolist()
    kwargs = {
        "query_embeddings": [vector],
        "n_results": top_k,
        "include": ["documents", "metadatas", "distances"],
    }
    if scheme_name:
        kwargs["where"] = {"scheme_name": scheme_name}

    result = collection.query(**kwargs)
    chunks = [
        _to_chunk(
            result["ids"][0][i],
            result["metadatas"][0][i],
            result["documents"][0][i],
            result["distances"][0][i],
        )
        for i in range(len(result["ids"][0]))
    ]

    # A filter that matches nothing should never silently return nothing useful.
    if not chunks and scheme_name:
        result = collection.query(
            query_embeddings=[vector],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )
        chunks = [
            _to_chunk(
                result["ids"][0][i],
                result["metadatas"][0][i],
                result["documents"][0][i],
                result["distances"][0][i],
            )
            for i in range(len(result["ids"][0]))
        ]

    is_weak = bool(chunks) and chunks[0].distance > WEAK_MATCH_THRESHOLD
    return chunks, scheme_name, is_weak


def build_context(chunks: list[RetrievedChunk]) -> str:
    """
    Render retrieved chunks for the LLM prompt.

    Each block is labelled with its scheme, section and URL so the model can see
    which fact belongs to which scheme, and so the citation is auditable.
    """
    blocks = []
    for i, c in enumerate(chunks, 1):
        blocks.append(
            f"[{i}] Scheme: {c.scheme_name}\n"
            f"    Section: {c.section}\n"
            f"    Source: {c.source_url}\n"
            f"    Facts: {c.text}"
        )
    return "\n\n".join(blocks)