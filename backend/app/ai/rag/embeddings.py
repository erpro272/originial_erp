"""Local embeddings (free, no API): fastembed's BAAI/bge-small-en-v1.5 (384 dims, ONNX on CPU), downloaded once.
If it can't be loaded (no internet on first run, or EMBEDDINGS_BACKEND=hash) a deterministic hashing embedder is used:
words and word pairs hashed into 384 signed buckets (lexical similarity only). Chunks remember which one made them."""

import hashlib
import logging
import math
import re
import threading
from functools import lru_cache
from itertools import pairwise
from typing import Protocol

from app.ai.rag.models import DIM
from app.core.config import get_settings

log = logging.getLogger(__name__)
WORD = re.compile(r"[a-z0-9]+(?:[-.][a-z0-9]+)*")


class Embedder(Protocol):
    name: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashEmbedder:
    name = f"hash-{DIM}"

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * DIM
        words = WORD.findall(text.lower())
        feats = words + [f"{a} {b}" for a, b in pairwise(words)]
        for f in feats:
            h = hashlib.blake2b(f.encode(), digest_size=8).digest()
            i = int.from_bytes(h[:4], "big") % DIM
            v[i] += 1.0 if h[4] & 1 else -1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]


class FastEmbedder:
    def __init__(self, model: str) -> None:
        from fastembed import TextEmbedding

        self._m = TextEmbedding(model)
        self.name = model

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(x) for x in v] for v in self._m.embed(texts, batch_size=32)]


_lock = threading.Lock()


def get_embedder() -> Embedder:
    """One embedder per process; concurrent first calls (startup warm-up + a question) wait for the same load."""
    with _lock:
        return _load()


@lru_cache
def _load() -> Embedder:
    s = get_settings()
    if s.embeddings_backend == "hash":
        return HashEmbedder()
    try:
        return FastEmbedder(s.embeddings_model)
    except Exception as exc:  # no network on first download, missing runtime...
        if s.embeddings_backend == "fastembed":
            raise
        log.warning(
            "embedding model %s unavailable (%s); using the hashing embedder",
            s.embeddings_model,
            type(exc).__name__,
        )
        return HashEmbedder()
