"""
Simulate the deployed start command: Streamlit ONLY, no ingestion step.

This is the decisive test now that chroma_db/ is committed and
`python src/ingest.py` has been removed from the start command. It runs the
real app.py, asks real questions (real Groq calls), and reports peak memory.

No ingestion happens here on purpose - that is the point.
"""

import sys
import threading
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

proc = psutil.Process()
peak = 0
stop = False


def rss() -> float:
    return proc.memory_info().rss / 1048576


def watch() -> None:
    global peak
    while not stop:
        peak = max(peak, rss())
        threading.Event().wait(0.01)


threading.Thread(target=watch, daemon=True).start()

# Prove the committed store is good BEFORE the app touches it.
sys.path.insert(0, str(ROOT / "src"))
import ingest  # noqa: E402

col = ingest.get_collection(ingest.get_client(), create=False)
n = col.count()
print("=== committed store (no ingestion run) ===")
print(f"  collection     : {ingest.COLLECTION_NAME}")
print(f"  vectors        : {n}")
print(f"  manifest ok    : {ingest.MANIFEST.exists()}")
if n != 46:
    print(f"  *** EXPECTED 46 VECTORS, FOUND {n} - DO NOT COMMIT ***")
    sys.exit(1)

from streamlit.testing.v1 import AppTest  # noqa: E402

at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=300)
at.run()
print(f"\n=== real app.py, no ingest ===")
print(f"  interpreter            : {rss():6.0f} MB")
print(f"  after first render     : {rss():6.0f} MB")

QUESTIONS = [
    "What is the expense ratio of HDFC Small Cap?",
    "Should I buy HDFC Large Cap?",
    "What is the lock-in period of HDFC ELSS?",
]
for q in QUESTIONS:
    at.chat_input[0].set_value(q).run()
    print(f"  after question         : {rss():6.0f} MB")

print(f"\n  chat messages rendered : {len(at.chat_message)}")

stop = True
print()
print("=" * 62)
print(f"PEAK, streamlit only, no ingest : {peak:6.0f} MB")
print(f"Render free budget               : {512:6.0f} MB")
print(f"headroom                         : {512 - peak:6.0f} MB")
print(f"verdict                          : {'FITS' if peak < 512 else 'OVER BUDGET'}")
print("=" * 62)
print(f"exceptions in app                : {len(at.exception)}")
print(f"torch imported                   : {'torch' in sys.modules}")
print(f"transformers imported            : {'transformers' in sys.modules}")