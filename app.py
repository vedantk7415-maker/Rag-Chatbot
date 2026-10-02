"""
Phase 6: Streamlit front end.

Run with:
    streamlit run app.py

The UI is a thin shell. All behaviour lives in src/, so the demo and the sample
script cannot drift apart - this file contains no retrieval, prompting or
formatting logic of its own.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

# src/ is not a package, so make it importable before pulling anything in.
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import formatter  # noqa: E402
import generator as gen  # noqa: E402
import guardrails  # noqa: E402
import ingest  # noqa: E402
import retriever  # noqa: E402

st.set_page_config(page_title="HDFC MF Facts Bot", page_icon="📊", layout="centered")

SCHEME_LINES = [
    "HDFC Large Cap Fund - Direct Growth",
    "HDFC Flexi Cap Fund - Direct Growth",
    "HDFC ELSS Tax Saver Fund - Direct Growth",
    "HDFC Small Cap Fund - Direct Growth",
    "HDFC Balanced Advantage Fund - Direct Growth",
]

SAMPLE_QUESTIONS = [
    "What is the expense ratio of HDFC Large Cap?",
    "What is the exit load of HDFC ELSS Tax Saver?",
    "What is the minimum SIP amount for HDFC Small Cap?",
    "What is the lock-in period of HDFC ELSS Tax Saver?",
    "What is the benchmark of HDFC Balanced Advantage Fund?",
    "What is the riskometer rating of HDFC Flexi Cap?",
    "Who manages HDFC Large Cap Fund?",
    "How do I download a capital gains statement?",
    "Should I buy HDFC Small Cap?",
    "Which HDFC fund gave better returns?",
]


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
def warm_up():
    """Force the MiniLM weights to load before the first real question."""
    ingest.get_model()
    return True


# --------------------------------------------------------------------------- #
# Sidebar
# --------------------------------------------------------------------------- #

status = corpus_status()

with st.sidebar:
    st.title("📊 HDFC MF Facts Bot")
    st.caption("Facts-only RAG over a small public corpus. Class demo.")

    if status["chunks"] > 0:
        st.success(f"{status['chunks']} chunks indexed")
    else:
        st.error("Vector store is empty. Run: python src/ingest.py")

    st.markdown("**Corpus** - 6 public Groww pages, no blogs, no third-party data:")
    for line in SCHEME_LINES:
        st.markdown(f"- {line}")
    st.markdown("- Groww guide: downloading a capital gains statement")

    st.markdown("---")
    st.markdown("**Try a question**")
    for q in SAMPLE_QUESTIONS:
        if st.button(q, key=f"s_{q}", use_container_width=True):
            st.session_state.pending = q

    st.markdown("---")
    st.caption(f"Model: `{status['model']}` · temperature 0")
    st.warning(
        "Educational demo. Not investment advice. Never enter PAN, Aadhaar, "
        "account or folio number, OTP, email or phone - the bot will refuse and "
        "will not store them."
    )

# --------------------------------------------------------------------------- #
# Main chat
# --------------------------------------------------------------------------- #

st.header("Ask a question about these five HDFC mutual funds")
st.caption(
    "Answers come only from the ingested pages. Maximum 3 sentences, one source "
    "link, and the date the data was collected."
)

if "messages" not in st.session_state:
    st.session_state.messages = []
if "pending" not in st.session_state:
    st.session_state.pending = None

if st.button("Clear conversation", use_container_width=False):
    st.session_state.messages = []
    st.rerun()


def render(result: gen.AnswerResult) -> None:
    """Show the answer, plus the evidence behind it."""
    with st.chat_message("assistant"):
        st.markdown(result.answer)

        # Transparency panel: show what was actually retrieved and why. This is
        # the part that makes the RAG visible during a demo.
        if result.chunks_used:
            with st.expander(f"Retrieved context ({len(result.chunks_used)} chunks)"):
                if result.scheme_detected:
                    st.caption(
                        f"Scheme filter applied: `{result.scheme_detected}` - this is "
                        "an exact metadata match, not a guess from the vector score."
                    )
                for c in result.chunks_used:
                    st.markdown(f"**{c.section}** · distance `{c.distance}`")
                    st.text(c.text)
                    st.caption(c.source_url)

        if result.blocked:
            label = {
                "pii": "🔒 Blocked: personal information detected",
                "advice": "🚫 Blocked: investment advice request",
                "performance": "🚫 Blocked: performance / returns request",
            }.get(result.block_kind, "🚫 Blocked")
            st.caption(f"{label}. Not sent to the language model.")
        elif not result.in_sources:
            st.caption("ℹ️ Not found in the ingested sources.")


for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])

question = st.chat_input("Ask about expense ratio, exit load, SIP, benchmark, lock-in...") or st.session_state.pending
st.session_state.pending = None

if question:
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    warm_up()

    try:
        with st.spinner("Retrieving and composing..."):
            result = gen.answer_question(question)
    except gen.MissingAPIKey:
        st.error(
            "GROQ_API_KEY is not set. Add it to the `.env` file in the project "
            "root as `GROQ_API_KEY=gsk_...` and restart the app."
        )
    except Exception as exc:  # noqa: BLE001 - never show a raw traceback to a user
        st.error(f"Something went wrong: {type(exc).__name__}")
        st.caption(str(exc)[:300])
    else:
        st.session_state.messages.append({"role": "assistant", "content": result.answer})
        render(result)

if not st.session_state.messages:
    st.info(
        "No returns or performance figures — those are excluded from the corpus "
        "on purpose. For official figures, use the AMC's factsheet."
    )
