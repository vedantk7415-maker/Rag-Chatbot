"""
Measure ingest.py IN-PROCESS.

Windows underreports child-process RSS through psutil on this machine - a fully
loaded Streamlit server also read as 4 MB - so subprocess measurement is
unreliable. Measuring self from inside the process is the trustworthy approach,
which is why samples/measure_app.py produced believable numbers.
"""

import shutil
import sys
import threading
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
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

# Simulate a fresh Render container: no vector store on disk.
store = ROOT / "chroma_db"
if store.exists():
    shutil.rmtree(store)
    print("removed chroma_db/ to simulate a clean container\n")

print(f"  before ingest            : {rss():6.0f} MB")

import ingest  # noqa: E402

chunks = ingest.run_ingest(rebuild=False)
print(f"  after ingest             : {rss():6.0f} MB")

stop = True
print()
print("=" * 58)
print(f"chunks embedded           : {len(chunks)}")
print(f"ingest.py PEAK RSS        : {peak:6.0f} MB")
print(f"Render free budget        : {512:6.0f} MB")
print(f"headroom                  : {512 - peak:6.0f} MB")
print(f"verdict                   : {'FITS' if peak < 512 else 'OVER BUDGET'}")
print("=" * 58)
print(f"torch imported            : {'torch' in sys.modules}")
