"""
Phase 6: Streamlit front end.

Run with:
    streamlit run app.py

The UI is a thin shell. All behaviour lives in src/, so the demo and the sample
script cannot drift apart - this file contains no retrieval, prompting or
answer-formatting logic of its own.

What this file IS responsible for:
  * presentation - layout, styling, and how a finished answer is displayed
  * lifting the citation line that src/formatter.py appends, so it renders as a
    tidy hyperlink in a footer instead of a bare URL sitting in the prose
  * session-scoped chat history

What this file is NOT responsible for:
  * deciding what is true, safe or allowed. Guardrails, retrieval, prompting and
    the answer contract all live in src/ and are imported unchanged.

Chat state lives only in st.session_state. Nothing is written to disk and
nothing is logged.
"""

from __future__ import annotations

import html
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import streamlit as st

# src/ is not a package, so make it importable before pulling anything in.
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import generator as gen  # noqa: E402
import ingest  # noqa: E402

st.set_page_config(
    page_title="HDFC MF Facts Bot",
    page_icon="📊",
    layout="centered",
    initial_sidebar_state="expanded",
)

DISCLAIMER = "Facts-only. No investment advice."

# Shown in the sidebar so you can tell at a glance which build is live. Bump it
# when you change anything you want to verify after a deploy.
BUILD_ID = "2026-10-02-ui2"

# Exactly three, per the demo brief. Between them they exercise a numeric fact,
# a less obvious scheme, and a guardrail refusal. Anything else is one keystroke
# away in the chat box.
EXAMPLE_QUESTIONS = [
    "What is the expense ratio of HDFC Small Cap?",
    "What is the lock-in period of HDFC ELSS Tax Saver?",
    "Should I buy HDFC Large Cap?",
]

SCHEME_LINES = [
    "HDFC Large Cap Fund - Direct Growth",
    "HDFC Flexi Cap Fund - Direct Growth",
    "HDFC ELSS Tax Saver Fund - Direct Growth",
    "HDFC Small Cap Fund - Direct Growth",
    "HDFC Balanced Advantage Fund - Direct Growth",
]

# --------------------------------------------------------------------------- #
# Session state helpers (in memory only, never written to disk)
# --------------------------------------------------------------------------- #

if "messages" not in st.session_state:
    st.session_state.messages = []
if "pending" not in st.session_state:
    st.session_state.pending = None
if "show_retrieval" not in st.session_state:
    st.session_state.show_retrieval = False


def queue_question(question: str) -> None:
    """Sidebar example button -> runs that question on the next render."""
    st.session_state.pending = question


def clear_chat() -> None:
    st.session_state.messages = []
    st.session_state.pending = None


# --------------------------------------------------------------------------- #
# Citation parsing
#
# src/formatter.py appends two lines to every grounded answer:
#     Source: https://...
#     Last updated from sources: <date>
#
# Those are a contract with the user rather than prose, so the UI lifts them out
# of the body and shows them as a footer. Nothing is discarded - if a line is
# present, it is displayed.
# --------------------------------------------------------------------------- #

_SOURCE_RE = re.compile(r"^Source:[ \t]*(https?://\S+)[ \t]*$", re.MULTILINE)
_UPDATED_RE = re.compile(r"^(Last updated from sources:.*)$", re.MULTILINE)


def parse_answer(answer: str) -> dict:
    """Split a formatted answer into body text, citation URL and date line."""
    url_match = _SOURCE_RE.search(answer)
    date_match = _UPDATED_RE.search(answer)

    body = _SOURCE_RE.sub("", answer)
    body = _UPDATED_RE.sub("", body)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()

    return {
        "body": body,
        "url": url_match.group(1) if url_match else None,
        "updated": date_match.group(1).strip() if date_match else None,
    }


def link_label(url: str) -> str:
    """Turn a URL into a short human label, e.g. 'groww.in'."""
    host = urlparse(url).netloc or "source"
    return host.removeprefix("www.")


def render_footer(payload: dict) -> None:
    """Citation and date: small and quiet, so it reads as provenance."""
    parts: list[str] = []

    if payload.get("url"):
        safe_url = html.escape(payload["url"], quote=True)
        safe_label = html.escape(link_label(payload["url"]))
        parts.append(
            f'<a class="src" href="{safe_url}" target="_blank" '
            f'rel="noopener noreferrer">Source: {safe_label} &#8599;</a>'
        )

    if payload.get("updated"):
        parts.append(html.escape(payload["updated"]))

    if parts:
        st.markdown(
            f'<div class="srcfoot">{" &nbsp;·&nbsp; ".join(parts)}</div>',
            unsafe_allow_html=True,
        )


# --------------------------------------------------------------------------- #
# Cached resources - loaded once per server process, not once per question
# --------------------------------------------------------------------------- #


@st.cache_resource(show_spinner=False)
def corpus_status() -> dict:
    """Read the store once per server process, not once per keystroke."""
    try:
        collection = ingest.get_collection(ingest.get_client(), create=False)
        count = collection.count() if collection else 0
    except Exception:  # noqa: BLE001 - a broken store must not crash the app
        count = -1
    return {"chunks": count, "model": gen.GROQ_MODEL}


@st.cache_resource(show_spinner="Loading the embedding model...")
def warm_up() -> bool:
    """Force the embedding weights to load before the first real question."""
    ingest.get_model()
    return True


# --------------------------------------------------------------------------- #
# Styling - restrained on purpose
# --------------------------------------------------------------------------- #

st.markdown(
    """
<style>
  /* One accent colour plus neutral greys. Nothing here is load-bearing: if a
     Streamlit upgrade renames a selector, the layout still works. */
  .block-container { padding-top: 2.2rem; padding-bottom: 4rem; max-width: 46rem; }
  h1, h2, h3 { letter-spacing: -0.01em; }

  /* The citation footer: deliberately quiet, so it reads as provenance rather
     than as part of the answer. */
  .srcfoot {
      margin-top: 0.55rem;
      padding-top: 0.45rem;
      border-top: 1px solid rgba(128,128,128,0.22);
      font-size: 0.80rem;
      line-height: 1.6;
      color: rgba(110,110,110,1);
  }
  .srcfoot a.src { color: #2f6f9f; text-decoration: none; font-weight: 500; }
  .srcfoot a.src:hover { text-decoration: underline; }

  [data-testid="stChatMessage"] { margin-bottom: 0.35rem; }
  [data-testid="stChatMessageContent"] { font-size: 1.02rem; line-height: 1.65; }

  /* Small screens: stop long scheme names forcing a horizontal scroll. */
  @media (max-width: 640px) {
    .block-container { padding-left: 1rem; padding-right: 1rem; }
    [data-testid="stChatMessageContent"] { font-size: 0.98rem; }
  }
</style>
""",
    unsafe_allow_html=True,
)

# --------------------------------------------------------------------------- #
# Sidebar
# --------------------------------------------------------------------------- #

status = corpus_status()

with st.sidebar:
    st.markdown("### 📊 HDFC MF Facts Bot")

    st.markdown(
        f"<div style='font-size:0.82rem;color:#8a8a8a;margin:0.4rem 0 0.2rem'>"
        f"{DISCLAIMER}</div>",
        unsafe_allow_html=True,
    )

    if status["chunks"] > 0:
        st.caption(f"Corpus loaded · {status['chunks']} indexed passages")
    else:
        st.error("Vector store not found. Run: python src/ingest.py")

    with st.expander("Corpus · 6 public Groww pages"):
        for line in SCHEME_LINES:
            st.markdown(f"- {line}")
        st.markdown("- Groww guide: downloading a capital gains statement")

    st.markdown("---")
    st.markdown("**Try an example**")
    for question in EXAMPLE_QUESTIONS:
        st.button(
            question,
            key=f"example_{question}",
            use_container_width=True,
            on_click=queue_question,
            args=(question,),
        )

    with st.expander("Retrieval details"):
        st.caption(
            "Off during a demo. Turn on to show what was actually retrieved "
            "and which scheme filter was applied."
        )
        st.toggle(
            "Show retrieved passages per answer",
            key="show_retrieval",
        )

    st.markdown("---")
    st.caption(f"Model `{status['model']}` · temperature 0")

    # Build marker. An earlier deploy looked broken only because the old build
    # was still being served, and there was no way to tell from the UI which
    # commit was live. This makes that question answerable at a glance.
    st.caption(f"Build `{BUILD_ID}`")

    # Rendered before the chat input, so on the very first question this run
    # `messages` is still empty. Checking `pending` too means the button exists
    # on that same run instead of only after some later rerun.
    if st.session_state.messages or st.session_state.pending:
        st.button(
            "🗑 Clear chat", key="clear_chat", use_container_width=True,
            on_click=clear_chat,
        )

# --------------------------------------------------------------------------- #
# Header and welcome
# --------------------------------------------------------------------------- #

st.title("HDFC mutual fund facts")
st.markdown(
    f"<div style='font-size:0.92rem;color:#8a8a8a;margin-bottom:0.4rem'>"
    f"{DISCLAIMER}</div>",
    unsafe_allow_html=True,
)

if not st.session_state.messages:
    st.markdown(
        """
<div style="background:#f7f8fa;border:1px solid rgba(128,128,128,0.20);
            border-radius:10px;padding:1rem 1.15rem;margin:0.6rem 0 0.2rem">
<div style="font-weight:600;margin-bottom:0.35rem">Welcome 👋</div>
<div style="font-size:0.93rem;line-height:1.65;color:#444">
Ask me about <b>expense ratio, exit load, minimum SIP, benchmark, riskometer
rating, NAV, AUM, fund manager, ELSS lock-in</b>, or how to download a
capital-gains statement, for any of the five HDFC schemes listed in the
sidebar.
<br><br>
Every answer comes only from the pages I ingested, runs to at most three
sentences, and carries one source link. Returns and performance figures are
deliberately excluded from my sources, and I will not tell you whether to buy
a fund.
</div>
</div>
""",
        unsafe_allow_html=True,
    )

    st.markdown("")
    st.markdown("**Schemes covered**")
    st.markdown(
        "\n".join(f"- {line}" for line in SCHEME_LINES)
        + "\n- Groww guide: downloading a capital gains statement"
    )


# --------------------------------------------------------------------------- #
# Message rendering
# --------------------------------------------------------------------------- #

BLOCK_TITLES = {
    "pii": "🔒 Personal information detected",
    "advice": "🚫 Investment advice request",
    "performance": "🚫 Returns or performance request",
}


def render_retrieval(result: gen.AnswerResult) -> None:
    """
    Optional transparency panel - hidden by default.

    This is the part that makes the RAG visible if someone asks how it works,
    but it is noise during a normal demo, so it sits behind a toggle.
    """
    if not st.session_state.show_retrieval or not result.chunks_used:
        return

    with st.expander(f"Retrieved context ({len(result.chunks_used)} passages)"):
        if result.scheme_detected:
            st.caption(
                f"Scheme filter applied: `{result.scheme_detected}` - an exact "
                "metadata match, not a guess from the vector score."
            )
        for chunk in result.chunks_used:
            st.markdown(f"**{chunk.section}** · distance `{chunk.distance}`")
            st.text(chunk.text)
            st.caption(chunk.source_url)


def render_assistant(result: gen.AnswerResult) -> None:
    """One assistant turn: answer text, then a quiet provenance footer."""
    with st.chat_message("assistant"):
        payload = parse_answer(result.answer)

        if result.blocked:
            # The refusal itself is already a full, friendly answer written in
            # src/guardrails.py, including the educational link it requires.
            # Here we only frame it so it cannot be mistaken for a real answer.
            with st.container(border=True):
                st.markdown(
                    f"**{BLOCK_TITLES.get(result.block_kind, '🚫 Request blocked')}**"
                )
                st.markdown(payload["body"])
                st.caption(
                    "Not sent to the language model. Nothing was stored."
                )
            return

        st.markdown(payload["body"])
        render_footer(payload)

        if not result.in_sources:
            st.caption("ℹ️ Not found in the ingested sources.")

        render_retrieval(result)


def render_user(question: str) -> None:
    with st.chat_message("user"):
        st.markdown(question)


# --------------------------------------------------------------------------- #
# Chat loop
# --------------------------------------------------------------------------- #

for message in st.session_state.messages:
    if message["role"] == "user":
        render_user(message["content"])
    else:
        render_assistant(message["result"])

question = st.chat_input(
    "Ask about expense ratio, exit load, SIP, benchmark, lock-in..."
) or st.session_state.pending

st.session_state.pending = None

if question:
    render_user(question)
    st.session_state.messages.append({"role": "user", "content": question})

    warm_up()

    try:
        with st.spinner("Retrieving passages and composing an answer..."):
            result = gen.answer_question(question)
    except gen.MissingAPIKey:
        # No stack trace, no environment details - just what to do about it.
        st.error(
            "This bot needs a Groq API key before it can answer. Add "
            "`GROQ_API_KEY` to the `.env` file in the project root, then "
            "restart the app."
        )
    except Exception:  # noqa: BLE001 - never show a raw traceback to a user
        st.error(
            "I couldn't produce an answer just now - the language model or the "
            "vector store didn't respond. Please try that question again."
        )
    else:
        st.session_state.messages.append({"role": "assistant", "result": result})
        render_assistant(result)