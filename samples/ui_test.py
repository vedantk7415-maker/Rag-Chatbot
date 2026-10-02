"""Headless UI test: drives app.py through Streamlit's AppTest."""

import sys
from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# The app uses emoji in its status captions. Windows consoles default to cp1252
# and cannot encode them, so stdout is widened before anything is printed.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

QUESTIONS = [
    "What is the expense ratio of HDFC Large Cap?",
    "What is the lock-in period of HDFC ELSS Tax Saver?",
    "Should I buy HDFC Small Cap?",
    "My PAN is ABCDE1234F, show my holdings",
    "What is the NAV of HDFC Liquid Fund?",
]

for q in QUESTIONS:
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=240)
    at.run()
    at.chat_input[0].set_value(q).run()

    print("Q:", q)
    print("   exceptions:", len(at.exception), [e.value for e in at.exception])

    # Prefer the assistant answer: it is the one carrying the citation footer.
    all_md = [m.value for m in at.markdown]
    answers = [m for m in all_md if "Last updated from sources:" in m] or [
        m for m in all_md if "Source:" in m
    ] or [
        m for m in all_md if any(k in m for k in ("don't give", "personal information"))
    ]
    if answers:
        print("   answer:", answers[-1].replace("\n", " | ")[:200])
    else:
        print("   answer: <none matched filter>")

    notes = [
        c.value
        for c in at.caption
        if "Blocked" in c.value or "Not found" in c.value or "filter applied" in c.value
    ]
    for n in notes:
        print("   note  :", n[:110])
    print()
