"""Local embedding model (architecture §8.2–§8.3).

Wraps fastembed (ONNX, CPU) running `nomic-ai/nomic-embed-text-v1.5`. Adds the
model's task prefixes itself, because fastembed doesn't (Doc/retrieval-research.md
§5), and L2-normalises every vector so a dot product is a cosine similarity.

Never raises because embeddings are unavailable: `load()` returns None when the
`embed` extra isn't installed (e.g. Python 3.15) or the model isn't cached, and
callers fall back to BM25. Only ingestion is allowed to download the model.
"""
from __future__ import annotations

import hashlib
import logging
import threading
from pathlib import Path
from typing import Iterable

from bolosip import config

log = logging.getLogger("bolosip.embedder")


def document_text(chunk: dict) -> str:
    """The text embedded for a chunk: the fact plus its topic keywords (research §5.2)."""
    return f"{chunk['text']} {chunk.get('keywords', '')}".strip()


def corpus_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Embedder:
    """One loaded model. Thread-safe: inference calls are serialised with a lock."""

    def __init__(self, model, model_name: str):
        self._model = model
        self.model_name = model_name
        self._lock = threading.Lock()

    def _embed(self, texts: list[str]):
        import numpy as np

        with self._lock:
            vectors = np.asarray(list(self._model.embed(texts)), dtype=np.float32)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return vectors / norms

    def embed_documents(self, texts: Iterable[str]):
        return self._embed([config.EMBED_DOC_PREFIX + t for t in texts])

    def embed_query(self, text: str):
        return self._embed([config.EMBED_QUERY_PREFIX + text])[0]

    @property
    def dims(self) -> int:
        return int(self.embed_query("dimension probe").shape[0])


_cache: dict[tuple[str, str, bool], Embedder | None] = {}
_cache_lock = threading.Lock()


def load(model_name: str | None = None, cache_dir: Path | None = None, *,
         allow_download: bool = False) -> Embedder | None:
    """Load (once per process) the embedding model, or return None.

    allow_download=False (the default, used by the running app) never touches the
    network: the model must already be in the cache. Ingestion passes True.
    """
    s = config.SETTINGS
    model_name = model_name or s.embed_model
    cache_dir = Path(cache_dir or s.model_cache)
    key = (model_name, str(cache_dir), allow_download)
    with _cache_lock:
        if key in _cache:
            return _cache[key]
        _cache[key] = _try_load(model_name, cache_dir, allow_download)
        return _cache[key]


def _try_load(model_name: str, cache_dir: Path, allow_download: bool) -> Embedder | None:
    try:
        import numpy  # noqa: F401
        from fastembed import TextEmbedding
    except ImportError:
        log.info("embeddings unavailable: the 'embed' extra is not installed")
        return None
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        model = TextEmbedding(model_name=model_name, cache_dir=str(cache_dir),
                              local_files_only=not allow_download)
        return Embedder(model, model_name)
    except Exception as e:  # missing from cache, offline, corrupt download...
        log.info("embeddings unavailable: could not load %s (%s)", model_name, type(e).__name__)
        return None


def reset_cache() -> None:
    """For tests."""
    with _cache_lock:
        _cache.clear()
