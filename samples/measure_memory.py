"""Measure peak memory of the query path, the way the deployed app runs it."""

import os
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

# Print RSS from a background thread while the real work runs.
peak = 0
stop = False


def rss_mb() -> float:
    """Resident set size in MB, without importing psutil."""
    try:
        import psutil

        return psutil.Process().memory_info().rss / 1024 / 1024
    except ImportError:
        # Fall back to reading the Windows API via ctypes.
        import ctypes

        class PMC(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong),
                ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        c = PMC()
        c.cb = ctypes.sizeof(PMC)
        ctypes.windll.psapi.GetProcessMemoryInfo(
            ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(c), c.cb
        )
        return c.WorkingSetSize / 1024 / 1024


def watch():
    global peak
    while not stop:
        peak = max(peak, rss_mb())
        threading.Event().wait(0.05)


t = threading.Thread(target=watch, daemon=True)
t.start()

print(f"{'stage':<42} {'rss MB':>8} {'peak MB':>8}")
print("-" * 60)
print(f"{'baseline (interpreter only)':<42} {rss_mb():>8.0f} {peak:>8.0f}")

import chromadb  # noqa: E402

print(f"{'+ chromadb imported':<42} {rss_mb():>8.0f} {peak:>8.0f}")

import guardrails  # noqa: E402,F401
import ingest  # noqa: E402
import retriever  # noqa: E402

client = ingest.get_client()
col = ingest.get_collection(client, create=False)
print(f"{'+ chroma client + collection open':<42} {rss_mb():>8.0f} {peak:>8.0f}")

ingest.get_model()
print(f"{'+ embedding model LOADED':<42} {rss_mb():>8.0f} {peak:>8.0f}")

chunks, scheme, weak = retriever.retrieve("What is the expense ratio of HDFC Large Cap?")
print(f"{'+ question embedded + query run':<42} {rss_mb():>8.0f} {peak:>8.0f}")

stop = True
t.join(timeout=1)
print("-" * 60)
print(f"{'PEAK (query path only)':<42} {'':>8} {peak:>8.0f}")
print()
print(f"torch threads : {os.cpu_count()} logical CPUs available")
print(f"OMP_NUM_THREADS = {os.environ.get('OMP_NUM_THREADS', '<unset>')}")
print(f"budget         : 512 MB (Render free tier)")
print(f"headroom       : {512 - peak:.0f} MB")
print()
print("NOTE: Streamlit itself adds ~80-120 MB on top of this figure.")
