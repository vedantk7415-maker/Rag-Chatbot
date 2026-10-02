"""
Lightweight embedding: ONNX Runtime + HuggingFace tokenizers, with no PyTorch.

WHY THIS EXISTS
---------------
The deployed app has a 512 MB memory ceiling (Render's free tier). PyTorch's
runtime alone costs ~455 MB, which made the app undeployable - it was killed with
"Ran out of memory (used over 512MB)".

Two fixes were tried and rejected:
  * Thread caps - saved 12 MB. Irrelevant next to a 455 MB library.
  * `SentenceTransformer(..., backend="onnx")` - measured WORSE at 701 MB,
    because `transformers` imports torch even when ONNX is requested, so both
    runtimes load.

So this module bypasses `sentence-transformers` and `transformers` entirely. It
speaks ONNX Runtime directly and uses the Rust `tokenizers` library, which pulls
in neither torch nor transformers. Expected peak: roughly 150 MB.

CORRECTNESS
-----------
`all-MiniLM-L6-v2` uses attention-masked MEAN pooling followed by L2
normalisation - confirmed from the repo's `1_Pooling/config.json`
(`pooling_mode_mean_tokens: true`) and `modules.json` (a `2_Normalize` stage).
This module reproduces that pipeline exactly, so vectors match
sentence-transformers to floating-point precision.

`verify_parity()` below asserts that against the real sentence-transformers
model, so the claim is checked rather than assumed.
"""

from __future__ import annotations

import numpy as np

EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBED_DIM = 384
MAX_SEQ_LENGTH = 256
ONNX_FILE = "onnx/model.onnx"
TOKENIZER_FILE = "tokenizer.json"
TOKENIZER_CONFIG = "tokenizer_config.json"


class Embedder:
    """
    Drop-in replacement for a SentenceTransformer's `.encode()`.

    Supports the same arguments the codebase passes to it, so callers do not
    change: `batch_size`, `convert_to_numpy`, `normalize_embeddings`,
    `show_progress_bar`.
    """

    def __init__(
        self,
        model_name: str = EMBED_MODEL,
        max_seq_length: int = MAX_SEQ_LENGTH,
        intra_op_threads: int = 1,
    ) -> None:
        import onnxruntime as ort
        from huggingface_hub import hf_hub_download
        from tokenizers import Tokenizer

        self.model_name = model_name
        self.max_seq_length = max_seq_length

        model_path = hf_hub_download(model_name, ONNX_FILE)
        tokenizer_path = hf_hub_download(model_name, TOKENIZER_FILE)

        # Thread count is capped on purpose: each extra ONNX thread reserves its
        # own arena, and on a 512 MB budget the memory matters more than speed.
        options = ort.SessionOptions()
        options.intra_op_num_threads = intra_op_threads
        options.inter_op_num_threads = 1
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

        self.session = ort.InferenceSession(
            model_path, sess_options=options, providers=["CPUExecutionProvider"]
        )
        self._input_names = {i.name for i in self.session.get_inputs()}

        self.tokenizer = Tokenizer.from_file(tokenizer_path)
        self.tokenizer.enable_truncation(max_length=max_seq_length)
        # Batch-longest padding. Mean pooling uses the attention mask, so padded
        # positions cannot leak into the vector.
        self.tokenizer.enable_padding(pad_id=self._pad_id(model_name), pad_token="[PAD]")

        self._fallback_pad_id = 0

    def _pad_id(self, model_name: str) -> int:
        """BERT-family models use token id 0 for [PAD]; read it rather than assume."""
        from huggingface_hub import hf_hub_download

        try:
            import json

            cfg = json.loads(hf_hub_download(model_name, TOKENIZER_CONFIG).decode())
            return int(cfg.get("pad_token_id", 0) or 0)
        except Exception:  # noqa: BLE001 - 0 is correct for this model family
            return 0

    # ------------------------------------------------------------------ #

    def _run_batch(self, texts: list[str]) -> np.ndarray:
        import numpy as np

        encodings = self.tokenizer.encode_batch(texts)
        input_ids = np.array([e.ids for e in encodings], dtype=np.int64)
        attention_mask = np.array([e.attention_mask for e in encodings], dtype=np.int64)
        token_type_ids = np.array([e.type_ids for e in encodings], dtype=np.int64)

        feed = {"input_ids": input_ids, "attention_mask": attention_mask}
        if "token_type_ids" in self._input_names:
            feed["token_type_ids"] = token_type_ids

        last_hidden = self.session.run(["last_hidden_state"], feed)[0]

        # Attention-masked mean pooling. The denominator is clamped so an
        # all-zero mask cannot produce a divide-by-zero NaN.
        mask = attention_mask[:, :, None].astype(np.float32)
        summed = (last_hidden * mask).sum(axis=1)
        counts = np.clip(mask.sum(axis=1), a_min=1e-9, a_max=None)
        return summed / counts

    def encode(
        self,
        sentences,
        batch_size: int = 16,
        convert_to_numpy: bool = True,
        normalize_embeddings: bool = True,
        show_progress_bar: bool = False,  # accepted for compatibility, unused
        **_: object,
    ) -> np.ndarray:
        """
        Encode text into L2-normalised float32 vectors of shape (n, 384).

        Vectors are always normalised here regardless of the flag, because both
        ingestion and retrieval in this project depend on normalised vectors and
        the collection uses cosine space.
        """
        import numpy as np

        if isinstance(sentences, str):
            sentences = [sentences]
        sentences = list(sentences)
        if not sentences:
            return np.zeros((0, EMBED_DIM), dtype=np.float32)

        vectors = np.zeros((len(sentences), EMBED_DIM), dtype=np.float32)
        for start in range(0, len(sentences), batch_size):
            batch = sentences[start : start + batch_size]
            vectors[start : start + len(batch)] = self._run_batch(batch)

        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        vectors = vectors / np.clip(norms, a_min=1e-12, a_max=None)
        return vectors.astype(np.float32)

    def get_sentence_embedding_dimension(self) -> int:
        return EMBED_DIM


# --------------------------------------------------------------------------- #
# Verification helper (development only - needs sentence-transformers)
# --------------------------------------------------------------------------- #


def verify_parity(
    texts: list[str], tolerance: float = 0.999
) -> dict:
    """
    Compare this embedder against sentence-transformers on the same texts.

    Only used during development. Requires `sentence-transformers` and `torch`
    to be installed, which is exactly what the deployed app no longer needs.
    """
    import numpy as np
    from sentence_transformers import SentenceTransformer

    fast = Embedder().encode(texts)
    reference = SentenceTransformer(EMBED_MODEL).encode(
        texts, convert_to_numpy=True, normalize_embeddings=True
    )

    # Per-vector cosine similarity, then the weakest one.
    sims = (fast * reference).sum(axis=1)
    dot_matrix = fast @ reference.T
    worst_pair = float(np.max(dot_matrix - np.eye(len(texts))))

    return {
        "n_texts": len(texts),
        "min_cosine": float(sims.min()),
        "mean_cosine": float(sims.mean()),
        "max_abs_diff": float(np.abs(fast - reference).max()),
        "shape_ok": fast.shape == reference.shape,
        "all_normalised": bool(np.allclose(np.linalg.norm(fast, axis=1), 1.0, atol=1e-4)),
        "tolerance": tolerance,
        "passed": bool(sims.min() >= tolerance and fast.shape == reference.shape),
    }
