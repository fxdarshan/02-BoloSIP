"""Vector store: a local ChromaDB collection (architecture §8.4, decision D13).

* Embedded and local (`chromadb.PersistentClient` in data/chroma/), telemetry off.
* Records: one per chunk, id = chunk id, metadata scheme_id ("" for official
  notes), topic, kind ("scheme" / "official"). Cosine distance; score = 1 - distance.
* Source of truth: data/embeddings.npy + data/embeddings.json (committed). The
  collection is rebuilt from them whenever it is missing or out of date, so
  Chroma's binary files never go into git and no model run is needed to rebuild.
* Never raises for a missing extra or a broken folder: `open_store()` returns None
  and the retriever falls back to BM25.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import threading
from pathlib import Path

from bolosip import config

log = logging.getLogger("bolosip.vectorstore")


def load_vectors(npy: Path | None = None, meta: Path | None = None):
    """(vectors, meta) from the committed files, or (None, None)."""
    npy, meta = npy or config.EMBEDDINGS_NPY, meta or config.EMBEDDINGS_META
    try:
        import numpy as np
        return np.load(npy), json.loads(meta.read_text(encoding="utf-8"))
    except Exception:
        return None, None


def save_vectors(vectors, meta: dict, npy: Path | None = None, meta_path: Path | None = None) -> None:
    """Write both files atomically (temp file + rename)."""
    import numpy as np

    npy, meta_path = npy or config.EMBEDDINGS_NPY, meta_path or config.EMBEDDINGS_META

    tmp_npy = npy.with_name(npy.name + ".tmp.npy")
    with open(tmp_npy, "wb") as f:
        np.save(f, vectors.astype(np.float32))
    tmp_meta = meta_path.with_name(meta_path.name + ".tmp")
    tmp_meta.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp_npy, npy)
    os.replace(tmp_meta, meta_path)


class VectorStore:
    def __init__(self, collection):
        self._col = collection
        self._lock = threading.Lock()

    @property
    def count(self) -> int:
        return self._col.count()

    @property
    def texts_sha256(self) -> str | None:
        return (self._col.metadata or {}).get("texts_sha256")

    def query(self, vector, scheme_id: str | None = None, n: int = 5) -> list[tuple[str, float]]:
        """[(chunk_id, cosine_score)], best first. With a scheme, only that scheme's facts
        and the official notes are searched (architecture §8.1)."""
        where = {"$or": [{"scheme_id": scheme_id}, {"kind": "official"}]} if scheme_id else None
        with self._lock:
            res = self._col.query(query_embeddings=[list(map(float, vector))], n_results=n, where=where,
                                  include=["distances"])
        return [(cid, 1.0 - float(d)) for cid, d in zip(res["ids"][0], res["distances"][0])]


def _client(chroma_dir: Path):
    import chromadb
    from chromadb.config import Settings

    chroma_dir.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(chroma_dir),
                                     settings=Settings(anonymized_telemetry=False, allow_reset=True))


def build(vectors, chunks: list[dict], meta: dict, chroma_dir: Path | None = None) -> VectorStore:
    """(Re)create the collection from vectors whose rows follow meta['chunk_ids']."""
    chroma_dir = Path(chroma_dir or config.SETTINGS.chroma_dir)
    client = _client(chroma_dir)
    try:
        client.delete_collection(config.CHROMA_COLLECTION)
    except Exception:
        pass
    col = client.create_collection(
        config.CHROMA_COLLECTION, embedding_function=None,
        metadata={"hnsw:space": "cosine", "texts_sha256": meta["texts_sha256"],
                  "model": meta["model"]})
    by_id = {c["id"]: c for c in chunks}
    ids = meta["chunk_ids"]
    metadatas = [{"scheme_id": by_id[i]["scheme_id"] or "", "topic": by_id[i]["topic"],
                  "kind": "scheme" if by_id[i]["scheme_id"] else "official"} for i in ids]
    col.add(ids=ids, embeddings=[list(map(float, v)) for v in vectors], metadatas=metadatas)
    return VectorStore(col)


_store_cache: dict[str, VectorStore | None] = {}
_store_lock = threading.Lock()


def mismatch(vectors, meta: dict | None, chunks: list[dict]) -> str | None:
    """Why the saved vectors can't be used with these chunks, or None if they match.

    Besides the corpus hash, the chunk ids and row count must match exactly: once a
    mangled id in embeddings.json ("hdfcalanced-advantage:category", ISS-024) passed the
    hash check and crashed the Chroma rebuild."""
    if vectors is None or not meta:
        return "data/embeddings.npy or .json missing"
    ids = meta.get("chunk_ids") or []
    want = [c["id"] for c in chunks]
    if len(ids) != len(vectors):
        return f"embeddings.json lists {len(ids)} chunks but embeddings.npy has {len(vectors)} rows"
    if ids != want:
        bad = next((i for i in ids if i not in set(want)), None) or next((i for i in want if i not in set(ids)), "order")
        return f"embeddings.json chunk ids don't match corpus.json (first difference: {bad})"
    return None


def open_store(chunks: list[dict], texts_sha256: str, chroma_dir: Path | None = None) -> VectorStore | None:
    """Open the collection for this corpus, rebuilding it from the committed vectors if it
    is missing or stale. None if Chroma isn't installed or the vectors don't match."""
    chroma_dir = Path(chroma_dir or config.SETTINGS.chroma_dir)
    key = f"{chroma_dir}|{texts_sha256}"
    with _store_lock:
        if key in _store_cache:
            return _store_cache[key]
        _store_cache[key] = _open(chunks, texts_sha256, chroma_dir)
        return _store_cache[key]


def _open(chunks, texts_sha256, chroma_dir) -> VectorStore | None:
    try:
        import chromadb  # noqa: F401
    except ImportError:
        log.info("vector store unavailable: chromadb is not installed")
        return None
    vectors, meta = load_vectors()
    if vectors is None or meta.get("texts_sha256") != texts_sha256:
        log.info("vector store unavailable: data/embeddings.npy is missing or doesn't match the corpus texts")
        return None
    problem = mismatch(vectors, meta, chunks)
    if problem:
        log.warning("vector store unavailable: %s (run ingest.py --embed-only)", problem)
        return None
    try:
        col = _client(chroma_dir).get_collection(config.CHROMA_COLLECTION)
        store = VectorStore(col)
        if store.texts_sha256 == texts_sha256 and store.count == len(meta["chunk_ids"]):
            return store
    except Exception:
        pass   # missing or unreadable: rebuild below
    try:
        return build(vectors, chunks, meta, chroma_dir)
    except Exception as e:
        log.warning("vector store rebuild failed (%s); removing %s and retrying once", type(e).__name__, chroma_dir)
        shutil.rmtree(chroma_dir, ignore_errors=True)
        try:
            return build(vectors, chunks, meta, chroma_dir)
        except Exception as e2:
            log.warning("vector store unavailable: %s", type(e2).__name__)
            return None


def reset_cache() -> None:
    """For tests."""
    with _store_lock:
        _store_cache.clear()
