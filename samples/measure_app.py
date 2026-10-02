"""Measure the real app.py, in-process, through three questions."""

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


def watch():
    global peak
    while not stop:
        peak = max(peak, rss())
        threading.Event().wait(0.02)


threading.Thread(target=watch, daemon=True).start()

from streamlit.testing.v1 import AppTest  # noqa: E402

print("=== baseline ===")
print(f"  python interpreter         : {rss():6.0f} MB")

at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=300)
at.run()
print(f"  after app.py first render  : {rss():6.0f} MB")

at.chat_input[0].set_value("What is the expense ratio of HDFC Large Cap?").run()
print(f"  after question 1 (LLM call): {rss():6.0f} MB")

at.chat_input[0].set_value("Should I buy HDFC Small Cap?").run()
at.chat_input[0].set_value("What is the lock-in period of HDFC ELSS?").run()
print(f"  after 3 questions          : {rss():6.0f} MB")

stop = True
print()
print("=" * 58)
print(f"PEAK, real app.py, 3 Qs : {peak:6.0f} MB")
print(f"Render free budget      : {512:6.0f} MB")
print(f"headroom                : {512 - peak:6.0f} MB")
print(f"verdict                 : {'FITS' if peak < 512 else 'OVER BUDGET'}")
print("=" * 58)
print(f"exceptions in app       : {len(at.exception)}")
print(f"torch imported          : {'torch' in sys.modules}")
print(f"transformers imported   : {'transformers' in sys.modules}")
print(f"sentence_transformers   : {'sentence_transformers' in sys.modules}")
