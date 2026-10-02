"""
Phase 5 (part 2): Output formatting.

The formatter is the last line of defence for the answer contract. Whatever the
LLM returns, the user sees something that satisfies the brief:

  - at most 3 sentences
  - exactly ONE citation link, added by us and stripped from the LLM output
  - ends with "Last updated from sources: <date>"

Doing this in code rather than in the prompt is deliberate. A prompt instruction
is a request; a formatter is a guarantee. The LLM can be talked into a fourth
sentence, but it cannot talk this module into emitting two links.
"""

from __future__ import annotations

import re

MAX_SENTENCES = 3

FOOTER_PREFIX = "Last updated from sources:"

# Any URL the model emitted. We remove these and substitute our own single
# canonical citation, so the "exactly one link" rule holds even if the model
# helpfully adds three of its own.
_URL_RE = re.compile(r"https?://\S+|www\.\S+")

# Markdown/HTML decoration that adds nothing for a chat bubble.
_MD_NOISE_RE = re.compile(r"[*_`#]+")

# "**Answer:**" style lead-ins the model likes to add.
_PREFIX_RE = re.compile(r"^\s*(?:answer|a)\s*[:\-]\s*", re.IGNORECASE)

# A sentence boundary: . ! or ? followed by whitespace. The whitespace
# requirement is what stops "1.04%" and "Rs 1.21" from being split.
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


# A sentence that is nothing but a pointer: it has a URL and no numbers. LLMs
# emit these constantly ("For more details, see https://..."). Because we supply
# the citation ourselves, the whole sentence is dropped rather than stripped
# down to a dangling "See and for details".
_REFERENCE_ONLY_RE = re.compile(
    r"https?://|www\.", re.IGNORECASE
)
_HAS_DIGIT_RE = re.compile(r"\d")

# After removing a URL, a connective is left with nothing to attach to.
# "at https://x.com" -> "at" -> drop the orphan word with its conjunction.
_DANGLING_RE = re.compile(
    r"\b(?:see|refer|visit|read|check|at|on|from|to|of|in|available|link|browse)"
    r"\s+(?:and|or)\b",
    re.IGNORECASE,
)


def strip_links(text: str) -> str:
    """Remove URLs and tidy the whitespace and orphans they leave behind."""
    cleaned = _URL_RE.sub("", text)
    cleaned = _DANGLING_RE.sub("", cleaned)
    cleaned = re.sub(r"\s*,\s*,", ",", cleaned)
    cleaned = re.sub(r"\.\s*\.", ".", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\s+([.,;:])", r"\1", cleaned)
    return cleaned


def _drop_reference_only_sentences(text: str) -> str:
    """Delete sentences whose only job was to carry a link."""
    kept = []
    for sentence in split_sentences(text):
        if _REFERENCE_ONLY_RE.search(sentence) and not _HAS_DIGIT_RE.search(sentence):
            continue
        kept.append(sentence)
    return " ".join(kept)


def clean_answer(text: str) -> str:
    """Normalise LLM output into plain prose."""
    if not text:
        return ""
    # Models sometimes answer with a bulleted list; flatten it to sentences.
    lines = [re.sub(r"^\s*(?:[-*•]|\d+[.)])\s+", "", ln) for ln in text.splitlines()]
    joined = " ".join(ln for ln in lines if ln.strip())
    joined = _MD_NOISE_RE.sub("", joined)
    joined = _PREFIX_RE.sub("", joined)
    joined = _drop_reference_only_sentences(joined)
    joined = strip_links(joined)
    return re.sub(r"\s+", " ", joined).strip()


def split_sentences(text: str) -> list[str]:
    """
    Split on real sentence boundaries only.

    The `(?<=[.!?])\\s+` form is deliberate: a period followed by whitespace is a
    sentence end, while a period between digits ("1.04%") or inside an amount
    ("Rs 1,405.49") has no whitespace after it and is left alone.
    """
    if not text:
        return []
    parts = [p.strip() for p in _SENT_SPLIT_RE.split(text) if p.strip()]
    return parts


def enforce_sentence_limit(text: str, max_sentences: int = MAX_SENTENCES) -> str:
    """
    Keep the first `max_sentences` sentences.

    Truncation is a real risk to answer quality, so `generator` is told the limit
    in the prompt and this is only a safety net. If truncation happens anyway we
    make sure the text still ends cleanly rather than mid-word.
    """
    sentences = split_sentences(text)
    if len(sentences) <= max_sentences:
        return " ".join(sentences)
    kept = sentences[:max_sentences]
    out = " ".join(kept).strip()
    out = re.sub(r"[\s,;:]+$", "", out)
    if out and out[-1] not in ".!?":
        out += "."
    return out


def format_answer(
    answer: str,
    source_url: str,
    last_updated: str,
    max_sentences: int = MAX_SENTENCES,
) -> str:
    """
    Assemble the final user-visible reply.

    `source_url` is the citation for the chunk the answer actually came from. We
    pass one URL in and get one URL out.
    """
    body = enforce_sentence_limit(clean_answer(answer), max_sentences)
    if not body:
        body = "I could not produce an answer from the retrieved sources."

    date = (last_updated or "unknown").strip()
    return (
        f"{body}\n\n"
        f"Source: {source_url}\n"
        f"{FOOTER_PREFIX} {date}"
    )


def format_unavailable(topic: str = "that question") -> str:
    """
    The honest failure answer: nothing matched the sources.

    No citation link here on purpose - there is no source to cite, and inventing
    one would be worse than admitting the gap.
    """
    return (
        f"I don't have {topic} in my sources, so I can't answer it without making "
        f"something up.\n\n"
        f"I only cover the facts published on the public HDFC scheme pages for the "
        f"five schemes in my corpus: expense ratio, exit load, minimum and maximum "
        f"SIP, benchmark, riskometer rating, NAV, AUM, fund manager, ELSS lock-in, "
        f"and how to download a capital-gains statement.\n\n"
        "Try asking about one of those. Facts-only. No investment advice."
    )


def format_scope(schemes: list[str]) -> str:
    """
    The answer to "which funds do you cover?" and similar meta questions.

    This exists because the alternative was genuinely bad. A visitor asking what
    the bot covers got "I don't have that information in my sources" - which is
    technically honest and practically useless, and it is a very likely first
    question from an examiner.

    The list comes from data/sources.csv, so it is read from the corpus rather
    than written from memory. No citation is attached, for the same reason
    `format_unavailable` omits one: this describes the corpus itself instead of
    reporting a figure from a single page, so there is no one page to point at.

    Three sentences, matching MAX_SENTENCES.
    """
    listing = "; ".join(schemes)
    return (
        f"I cover five HDFC equity schemes: {listing}.\n\n"
        "For any of them I can report expense ratio, exit load, minimum and "
        "maximum SIP, benchmark, riskometer rating, NAV, AUM, fund manager and "
        "ELSS lock-in, plus how to download a capital-gains statement.\n\n"
        "Returns and performance figures are excluded on purpose. Facts-only. "
        "No investment advice."
    )
