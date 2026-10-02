"""
Phase 5 (part 3): Generation and the query pipeline.

This module owns the whole path a question takes:

    guardrails -> retriever -> Groq -> formatter

The API key is read from the environment via .env and is never written into
source, printed, or logged. `.env` is gitignored.

Note on why the pipeline lives here and not in app.py: Phase 6's UI needs to call
exactly this sequence for both the sample-QA script and the chat app, and having
one implementation means the demo and the tests cannot drift apart.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from dotenv import load_dotenv

import formatter
import guardrails
import ingest
import retriever

load_dotenv()

# Overridable so the demo can switch models without a code change.
#
# The default was set by listing the models this key can actually reach, rather
# than by assuming. llama-3.3-70b-versatile is the model most tutorials use, but
# it is not served on this account - a hardcoded guess would have failed on the
# first live call. gpt-oss-120b is the strongest general-purpose text model
# available here; the alternatives are gpt-oss-20b and qwen3.8-27b.
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

# The model emits this exact string when the retrieved context cannot answer.
# A sentinel is far more reliable than trying to detect refusal in prose.
NOT_IN_SOURCES = "NOT_IN_SOURCES"

SYSTEM_PROMPT = """\
You are a facts-only mutual fund information assistant built for a class \
demonstration. You report published facts about specific HDFC mutual fund schemes.

ABSOLUTE RULES
1. Use ONLY the numbered [SOURCE] blocks in the CONTEXT. You have no other \
knowledge of these funds. Never fill a gap from memory or general knowledge.
2. Answer in at most 3 sentences. Plain prose only.
3. Copy every figure exactly as written in the context, including units and \
decimals (for example "1.04%", "Rs 100", "3 years", "NIFTY 100 TRI"). Never \
round, convert, recompute, infer or adjust a number.
4. Never give investment advice, a recommendation, an opinion, or a judgement \
about whether a fund is good, bad, safe or suitable. Report facts only.
5. Never state, compare, rank or estimate returns, performance, CAGR, profit or \
loss. If the question asks for these, they are not available to you.
6. Never output URLs, links, markdown, bullet points, headings or emoji.
7. Never write the words "Source" or "Last updated" - those are added for you.
8. Name the scheme explicitly in your answer so it is never ambiguous which fund \
you are describing.
9. If the context does not contain the answer, reply with exactly: NOT_IN_SOURCES

CONTEXT
{context}
"""


class MissingAPIKey(RuntimeError):
    """Raised when the pipeline needs Groq but no key is configured."""


# --------------------------------------------------------------------------- #
# Corpus-scope questions
#
# "Which funds do you cover?" is a very likely first question, and before this
# existed it was answered with "I don't have that information in my sources".
# That is technically honest and practically useless - and the LLM cannot fix
# it, because the prompt forbids answering from memory and no corpus chunk
# lists the schemes.
#
# So the answer is built from data/sources.csv instead: read from the corpus,
# never from the model's head. Deliberately narrow - an explicit coverage verb
# is required, so "which fund has a lower expense ratio" still reaches the
# guardrails instead of being answered with a list.
# --------------------------------------------------------------------------- #

_SCOPE_RE = re.compile(
    r"\b(?:which|what)\s+(?:5|five|these|this|are\s+these|are\s+this)\b"
    r"[^?]{0,30}\b(?:funds?|schemes?)\b"
    r"|\b(?:funds?|schemes?)\b[^?]{0,25}"
    r"\b(?:do\s+you\s+(?:cover|support|know)|you\s+cover|in\s+your\s+(?:corpus|sources))\b"
    r"|\blist\s+(?:the\s+|your\s+|all\s+)?(?:5\s+|five\s+)?(?:funds?|schemes?)\b"
    r"|\bwhat\s+can\s+you\s+(?:tell|answer|help)\b",
    re.IGNORECASE,
)


def is_scope_question(question: str) -> bool:
    """True for questions about which schemes the bot covers."""
    return bool(_SCOPE_RE.search(question))


def corpus_schemes() -> list[str]:
    """The scheme names in the corpus, read from data/sources.csv."""
    return [
        source.scheme_name
        for source in ingest.read_sources()
        if source.source_type == "scheme"
    ]


def get_api_key() -> str:
    """
    Read GROQ_API_KEY from the environment.

    The value is used and discarded; it is never returned to a caller that would
    print it, never written to a file, and never included in any error message.
    """
    key = os.getenv("GROQ_API_KEY", "").strip()
    if not key:
        raise MissingAPIKey(
            "GROQ_API_KEY is not set.\n"
            "Add it to the .env file in the project root:\n"
            "    GROQ_API_KEY=gsk_...\n"
            "Get a free key at https://console.groq.com/keys"
        )
    return key


def get_client():
    """Groq client, constructed lazily so tests can run without a key."""
    from groq import Groq

    return Groq(api_key=get_api_key())


# --------------------------------------------------------------------------- #
# Generation
# --------------------------------------------------------------------------- #


def generate_answer(question: str, context: str, model: str = GROQ_MODEL) -> str:
    """One completion. Temperature 0 so repeated demo runs are reproducible."""
    client = get_client()
    response = client.chat.completions.create(
        model=model,
        temperature=0,
        max_tokens=300,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT.format(context=context)},
            {"role": "user", "content": question},
        ],
    )
    return (response.choices[0].message.content or "").strip()


# --------------------------------------------------------------------------- #
# Pipeline
# --------------------------------------------------------------------------- #


@dataclass
class AnswerResult:
    question: str
    answer: str
    blocked: bool = False
    block_kind: str = "pass"
    scheme_detected: str | None = None
    chunks_used: list[retriever.RetrievedChunk] = field(default_factory=list)
    in_sources: bool = True
    weak_match: bool = False

    @property
    def top_section(self) -> str:
        return self.chunks_used[0].section if self.chunks_used else ""


def pick_citation(chunks: list[retriever.RetrievedChunk], scheme: str | None):
    """
    Choose which chunk's URL we cite.

    The top-ranked chunk is the default. If a scheme was detected but the top hit
    belongs to a different scheme - which the metadata filter already prevents,
    but a cheap assertion here means a future regression surfaces as a wrong
    citation rather than a silently mismatched one.
    """
    if not chunks:
        return None
    top = chunks[0]
    if scheme and top.scheme_name != scheme:
        for c in chunks:
            if c.scheme_name == scheme:
                return c
    return top


def answer_question(question: str, top_k: int = retriever.TOP_K) -> AnswerResult:
    """
    Full pipeline. Returns a finished, formatted answer either way.

    A guardrail block short-circuits before any retrieval or LLM call, so a
    PII-carrying question never reaches ChromaDB or Groq.
    """
    # 1. Guardrails - before retrieval, before the LLM.
    blocked = guardrails.check(question)
    if blocked.blocked:
        return AnswerResult(
            question=question,
            answer=blocked.response or "",
            blocked=True,
            block_kind=blocked.kind,
            scheme_detected=blocked.scheme_name,
            # Nothing was retrieved, so nothing came from the sources. Leaving
            # this True would let a caller report a blocked answer as grounded.
            in_sources=False,
        )

    # 2. "Which funds do you cover?" - answered from data/sources.csv, never
    #    from the model's memory, so it bypasses both retrieval and the LLM.
    if is_scope_question(question):
        return AnswerResult(
            question=question,
            answer=formatter.format_scope(corpus_schemes()),
            # These names come from the corpus itself, so the answer really is
            # grounded - unlike an unmatched question.
            in_sources=True,
        )

    # 3. Retrieval, with an exact scheme filter when one is named.
    chunks, scheme, weak = retriever.retrieve(question, top_k=top_k)

    # 4. Weak or empty match: say so rather than let the model improvise.
    if weak or not chunks:
        return AnswerResult(
            question=question,
            answer=formatter.format_unavailable("that information"),
            scheme_detected=scheme,
            chunks_used=chunks,
            in_sources=False,
            weak_match=weak,
        )

    # 5. Generate from the retrieved context only.
    context = retriever.build_context(chunks)
    raw = generate_answer(question, context)

    # 6. The sentinel means the model judged the context insufficient.
    if NOT_IN_SOURCES in raw.upper() or not raw.strip():
        return AnswerResult(
            question=question,
            answer=formatter.format_unavailable("that information"),
            scheme_detected=scheme,
            chunks_used=chunks,
            in_sources=False,
            weak_match=weak,
        )

    # 7. Format: <=3 sentences, exactly one citation, dated footer.
    citation = pick_citation(chunks, scheme)
    answer = formatter.format_answer(raw, citation.source_url, citation.last_updated)
    return AnswerResult(
        question=question,
        answer=answer,
        scheme_detected=scheme,
        chunks_used=chunks,
        in_sources=True,
        weak_match=weak,
    )
