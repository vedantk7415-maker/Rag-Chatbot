"""Compare memory cost: PyTorch backend vs ONNX backend, with/without thread caps."""

import os
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

# Thread caps must be set BEFORE torch/onnxruntime import.
caps = os.environ.get("CAP_THREADS", "0") == "1"
if caps:
    os.environ["OMP_NUM_THREADS"] = "1"
    os.environ["MKL_NUM_THREADS"] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"

import psutil  # noqa: E402

peak = 0
stop = False


def rss() -> float:
    return psutil.Process().memory_info().rss / 1048576


def watch():
    global peak
    while not stop:
        peak = max(peak, rss())
        threading.Event().wait(0.02)


t = threading.Thread(target=watch, daemon=True)
t.start()

backend = os.environ.get("BACKEND", "torch")
print(f"=== backend={backend}  thread_caps={caps} ===")

import chromadb  # noqa: E402,F401
import ingest  # noqa: E402

before = rss()

from sentence_transformers import SentenceTransformer  # noqa: E402

if backend == "onnx":
    model = SentenceTransformer(ingest.EMBED_MODEL, backend="onnx")
else:
    import torch

    torch.set_num_threads(1 if caps else os.cpu_count())
    model = SentenceTransformer(ingest.EMBED_MODEL)

after_load = rss()

# Do real work: embed the 46 corpus chunks, exactly as ingest.py does.
chunks = ingest.make_chunks()
vecs = model.encode(
    [c.text for c in chunks], batch_size=16, normalize_embeddings=True
)
dim = vecs.shape[1]

stop = True
t.join(timeout=1)

print(f"  chromadb + baseline      : {before:7.0f} MB")
print(f"  after model load         : {after_load:7.0f} MB  (+{after_load - before:.0f})")
print(f"  after embedding 46 chunks: {rss():7.0f} MB")
print(f"  PEAK                     : {peak:7.0f} MB   dims={dim}")
print(f"  budget 512 MB            : {'OK  ' if peak < 512 else 'OVER'}  headroom {512 - peak:+.0f} MB")
print()
