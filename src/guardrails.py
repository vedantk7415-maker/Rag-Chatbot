"""
Phase 4: Guardrails.

These checks run BEFORE retrieval, so unsafe or out-of-scope questions never
reach the vector store or the LLM. Every check returns a ready-to-show response,
which means Phase 5 can simply short-circuit on `blocked=True`.

Three checks, in priority order:
  1. PII            - warn, discard, never log or store the input
  2. Advice/opinion - polite facts-only refusal + an educational link
  3. Performance    - no numbers computed or compared, point to the factsheet

Anything else passes through untouched.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ingest import read_sources

# --------------------------------------------------------------------------- #
# Links used in refusals. Both come from the ingested data, so they stay inside
# the project's "public sources only" rule.
# --------------------------------------------------------------------------- #

# The official AMC site. Every scheme page in data/raw/*.txt records this as the
# official AMC / Scheme Information Document (SID) link, and it is where the
# official factsheets live.
AMC_URL = "https://www.hdfcfund.com"

DISCLAIMER = "Facts-only. No investment advice."

# --------------------------------------------------------------------------- #
# Scheme detection
# --------------------------------------------------------------------------- #

# Short aliases so "HDFC ELSS", "elss tax saver" and "large cap" all resolve to a
# scheme. Phase 5's retriever imports detect_scheme() and must use these same
# aliases, otherwise the guardrail and the retriever can disagree about which
# scheme the user meant.
SCHEME_ALIASES: dict[str, list[str]] = {
    "HDFC Large Cap Fund - Direct Growth": [
        "large cap", "largecap", "hdfc large cap",
    ],
    "HDFC Flexi Cap Fund - Direct Growth": [
        "flexi cap", "flexicap", "hdfc flexi cap", "hdfc equity fund",
    ],
    "HDFC ELSS Tax Saver Fund - Direct Growth": [
        "elss", "tax saver", "taxsaver", "hdfc elss", "elss tax saver",
    ],
    "HDFC Small Cap Fund - Direct Growth": [
        "small cap", "smallcap", "hdfc small cap",
    ],
    "HDFC Balanced Advantage Fund - Direct Growth": [
        "balanced advantage", "balancedadvantage", "hdfc balanced advantage",
    ],
}


def detect_scheme(question: str) -> str | None:
    """
    Return the canonical scheme name if the question names exactly one scheme.

    Longest alias wins, so "balanced advantage" is never swallowed by a shorter
    overlapping alias. Returns None when no scheme, or more than one, is named:
    guessing between two schemes is exactly the failure mode we are guarding
    against, so the caller falls back to unfiltered retrieval.
    """
    text = question.lower()
    matches: list[tuple[int, str]] = []
    for scheme, aliases in SCHEME_ALIASES.items():
        best = max((len(a) for a in aliases if a in text), default=0)
        if best:
            matches.append((best, scheme))
    if not matches:
        return None
    matches.sort(reverse=True)
    if len(matches) > 1 and matches[0][0] == matches[1][0]:
        return None  # ambiguous
    return matches[0][1]


def source_url_for(scheme: str | None) -> str:
    """The citation URL for a scheme, falling back to the official AMC site."""
    if not scheme:
        return AMC_URL
    for src in read_sources():
        if src.scheme_name == scheme:
            return src.url
    return AMC_URL


# --------------------------------------------------------------------------- #
# 1. PII
# --------------------------------------------------------------------------- #

# Deliberately narrow patterns. A false positive blocks a legitimate question,
# which is worse here than a miss, so every pattern needs real structure.
PII_PATTERNS: dict[str, re.Pattern] = {
    "PAN": re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b"),
    "Aadhaar": re.compile(r"\b[2-9][0-9]{3}\s?[0-9]{4}\s?[0-9]{4}\b"),
    "email address": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b"),
    "phone number": re.compile(r"(?:\+91[-\s]?|\b0)?\b[6-9][0-9]{9}\b"),
    "OTP or 6-digit code": re.compile(r"\b[0-9]{6}\b"),
    "account or folio number": re.compile(
        r"\b(?:account|folio|pan|aadhaar)\s*(?:number|no\.?|num|#)\s*[:#]?\s*[A-Z0-9-]{4,}\b",
        re.IGNORECASE,
    ),
}


def detect_pii(question: str) -> list[str]:
    """Names of the PII types found. The matched text itself is never returned."""
    return [label for label, pattern in PII_PATTERNS.items() if pattern.search(question)]


# --------------------------------------------------------------------------- #
# 2. Advice / opinion
# --------------------------------------------------------------------------- #

ADVICE_PATTERNS = [
    r"\bshould\s+(?:i|we)\b",
    r"\bshould\s+.{0,30}\b(?:buy|sell|invest|redeem|switch|hold|start)\b",
    r"\b(?:can|should)\s+i\s+(?:buy|sell|invest|redeem|hold|start)\b",
    r"\b(?:is|are)\s+it\s+(?:a\s+)?(?:good|bad|wise|safe|worth)\b",
    r"\bworth\s+(?:investing|buying)\b",
    r"\bgood\s+time\s+to\b",
    r"\brecommend\b",
    r"\bsuggest\b",
    r"\badvice\b",
    r"\bopinion\b",
    r"\bwhich\s+(?:one|fund|scheme)\s+(?:should|is)\s+(?:i|best|right)\b",
    r"\bbest\s+(?:fund|scheme|option)\b",
    r"\bwhich\s+(?:fund|scheme)\s+(?:do|should|would)\s+(?:i|we)\b",
    r"\b(?:my|our)\s+portfolio\b",
    r"\bhow\s+(?:much|should\s+i)\s+(?:to\s+)?(?:invest|allocate)\b",
    r"\ballocat(?:e|ion)\b",
    r"\bhold\s+(?:this|it|them)\b",
    # "Is HDFC Small Cap a good buy?" - an opinion request with no should/can.
    r"\b(?:good|bad|wise|worthwhile|safe)\s+(?:buy|investment|invest|pick|choice|option)\b",
    r"\bworth\s+buying\b",
]
ADVICE_RE = re.compile("|".join(ADVICE_PATTERNS), re.IGNORECASE)


def is_advice(question: str) -> bool:
    return bool(ADVICE_RE.search(question))


# --------------------------------------------------------------------------- #
# 3. Performance / returns
# --------------------------------------------------------------------------- #

# "capital gains statement" is a tax-document question, not a performance
# question, and it must not be caught by the "gains" pattern below.
_PERFORMANCE_RE = re.compile(
    r"""
      \breturns?\b
    | \bperformance\b
    | \bperform(?:s|ed|ing)\b
    | \bhow\s+much\s+(?:did|has|have)\b
    | \bhow\s+(?:good|bad)\b
    | \bcagr\b
    | \byield\b
    | \bprofit\b
    | \b(?:made|making)\s+(?:a\s+)?(?:profit|loss|money)\b
    | \boutperform\w*\b
    | \b(?:better|best|worst)\s+(?:performing|performer)\b
    | \bcompare\b
    | \bvs\.?\b
    | \bversus\b
    | \bwhich\s+(?:fund|scheme)\s+(?:is|was|gave)\b
    | \b1\s*year\s+return\b
    | \bhistorical\s+return\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

_NON_PERFORMANCE = re.compile(
    r"\bcapital\s+gains?\s+statement\b|\bcapital\s+gains?\s+report\b", re.IGNORECASE
)


def is_performance(question: str) -> bool:
    if _NON_PERFORMANCE.search(question):
        return False
    return bool(_PERFORMANCE_RE.search(question))


# --------------------------------------------------------------------------- #
# Result type + responses
# --------------------------------------------------------------------------- #


@dataclass
class GuardrailResult:
    blocked: bool
    kind: str  # "pass" | "pii" | "advice" | "performance"
    response: str | None = None
    scheme_name: str | None = None
    pii_types: list[str] | None = None


def _pii_response(found: list[str]) -> str:
    kinds = ", ".join(found)
    return (
        "I can't accept personal information, so I did not process or store that "
        f"message (detected: {kinds}).\n\n"
        "I only answer scheme facts from public pages and never need your PAN, "
        "Aadhaar, account or folio number, OTP, email address or phone number.\n\n"
        "Please ask again without personal details, for example: "
        '"What is the exit load of HDFC Large Cap?"'
    )


def _advice_response(scheme: str | None) -> str:
    link = source_url_for(scheme)
    who = f" {scheme}" if scheme else ""
    return (
        f"I don't give investment advice or recommendations for{who}, so I can't "
        "answer that one.\n\n"
        "I can share verified facts only - expense ratio, exit load, minimum SIP, "
        "benchmark, riskometer rating, ELSS lock-in and how to download statements. "
        f"Start from the scheme's public page here: {link}\n\n"
        f"{DISCLAIMER}"
    )


def _performance_response(scheme: str | None) -> str:
    who = f" for {scheme}" if scheme else ""
    return (
        "I don't calculate, compare or quote returns"
        f"{who}. Return figures can change daily, so quoting them would be "
        "misleading.\n\n"
        f"For the official, current performance figures and factsheet, see the AMC "
        f"here: {AMC_URL}\n\n"
        f"{DISCLAIMER}"
    )


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def check(question: str) -> GuardrailResult:
    """
    Run all three checks. Priority: PII > advice > performance > pass.

    The input is never logged, echoed back or stored by this function. Only the
    *names* of the detected PII categories are kept, never the values.
    """
    scheme = detect_scheme(question)

    found = detect_pii(question)
    if found:
        return GuardrailResult(True, "pii", _pii_response(found), scheme, found)

    if is_advice(question):
        return GuardrailResult(True, "advice", _advice_response(scheme), scheme)

    if is_performance(question):
        return GuardrailResult(True, "performance", _performance_response(scheme), scheme)

    return GuardrailResult(False, "pass", None, scheme)