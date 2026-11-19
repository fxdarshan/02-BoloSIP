"""Inspect the embeddings stored in the local ChromaDB collection (Phase 3).

Reads the `bolosip_facts` collection in data/chroma/ directly, joins each record
with its chunk text from data/corpus.json, and prints it. Needs the `embed` extra,
so run it with the Python 3.12 environment (README, "Embeddings"):

    .venv/Scripts/python.exe scripts/show_embeddings.py                    # summary + first 10 records
    .venv/Scripts/python.exe scripts/show_embeddings.py --scheme hdfc-mid-cap
    .venv/Scripts/python.exe scripts/show_embeddings.py --topic exit_load --dims 12
    .venv/Scripts/python.exe scripts/show_embeddings.py --id hdfc-mid-cap:exit_load --full
    .venv/Scripts/python.exe scripts/show_embeddings.py --query "exit load of HDFC Mid Cap"
    .venv/Scripts/python.exe scripts/show_embeddings.py --csv data/embeddings_view.csv

Read-only: it never changes the collection. If the collection is missing or stale,
run `python ingest.py --embed-only` first.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bolosip import config  # noqa: E402


def _fmt_vec(v, n: int) -> str:
    head = ", ".join(f"{x:+.4f}" for x in v[:n])
    return f"[{head}{', …' if len(v) > n else ''}]"


def _short(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Show the chunk embeddings stored in ChromaDB.")
    ap.add_argument("--scheme", help="only this scheme id (e.g. hdfc-mid-cap), or 'official' for the notes")
    ap.add_argument("--topic", help="only this topic (e.g. exit_load)")
    ap.add_argument("--id", help="one chunk id (e.g. hdfc-mid-cap:exit_load)")
    ap.add_argument("--limit", type=int, default=10, help="records to print (0 = all; default 10)")
    ap.add_argument("--dims", type=int, default=8, help="vector values to show per record (default 8)")
    ap.add_argument("--full", action="store_true", help="print every one of the 768 values")
    ap.add_argument("--query", help="embed this question and show the 5 nearest chunks with cosine scores")
    ap.add_argument("--csv", type=Path, help="write all matching records (id, metadata, text, every dim) to CSV")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):          # ₹ and box characters on a Windows console
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    try:
        import numpy as np
        from bolosip import vectorstore
    except ImportError:
        print("Needs the 'embed' extra (numpy, chromadb). Use the Python 3.12 venv: "
              ".venv/Scripts/python.exe scripts/show_embeddings.py", file=sys.stderr)
        return 2
    try:
        import chromadb  # noqa: F401
    except ImportError:
        print("chromadb is not installed in this Python; use .venv/Scripts/python.exe", file=sys.stderr)
        return 2

    chroma_dir = config.SETTINGS.chroma_dir
    if not chroma_dir.exists():
        print(f"No ChromaDB folder at {chroma_dir}. Run: python ingest.py --embed-only", file=sys.stderr)
        return 1
    client = vectorstore._client(chroma_dir)
    try:
        col = client.get_collection(config.CHROMA_COLLECTION)
    except Exception:
        print(f"Collection '{config.CHROMA_COLLECTION}' not found. Run: python ingest.py --embed-only",
              file=sys.stderr)
        return 1

    corpus_path = config.SETTINGS.corpus_path
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    by_id = {c["id"]: c for c in corpus["chunks"]}
    position = {cid: i for i, cid in enumerate(by_id)}

    # ---- Summary ------------------------------------------------------------
    cmeta = col.metadata or {}
    from bolosip import embedder
    current_sha = embedder.corpus_hash(corpus_path)
    data = col.get(include=["embeddings", "metadatas"])
    ids, metas = data["ids"], data["metadatas"]
    vecs = np.asarray(data["embeddings"], dtype=np.float32)
    order = sorted(range(len(ids)), key=lambda i: position.get(ids[i], 10**6))   # corpus order
    ids, metas, vecs = [ids[i] for i in order], [metas[i] for i in order], vecs[order]

    norms = np.linalg.norm(vecs, axis=1)
    print(f"ChromaDB folder : {chroma_dir}")
    print(f"Collection      : {col.name}   records: {col.count()}   dims: {vecs.shape[1]}")
    print(f"Model           : {cmeta.get('model')}   distance: {cmeta.get('hnsw:space')}")
    print(f"Corpus hash     : {str(cmeta.get('corpus_sha256'))[:16]}…  "
          f"({'matches' if cmeta.get('corpus_sha256') == current_sha else 'STALE: differs from'} data/corpus.json)")
    print(f"Vector norms    : min {norms.min():.4f}  max {norms.max():.4f}  (1.0 = L2-normalised)")
    kinds = {}
    for m in metas:
        kinds[m["kind"]] = kinds.get(m["kind"], 0) + 1
    print(f"Records by kind : {kinds}")
    npy, _ = vectorstore.load_vectors()
    if npy is not None and npy.shape == vecs.shape:
        meta_ids = json.loads(config.EMBEDDINGS_META.read_text(encoding="utf-8"))["chunk_ids"]
        ref = npy[[meta_ids.index(i) for i in ids]]
        print(f"vs embeddings.npy: max |difference| {float(np.abs(ref - vecs).max()):.2e} (Chroma stores float32)")
    print()

    # ---- Nearest chunks for a question ---------------------------------------
    if args.query:
        model = embedder.load()
        if model is None:
            print("The embedding model is not cached; run python ingest.py --embed-only", file=sys.stderr)
            return 1
        q = model.embed_query(args.query)
        res = col.query(query_embeddings=[list(map(float, q))], n_results=5)
        print(f'Query: "{args.query}"   (embedded as "{config.EMBED_QUERY_PREFIX}{args.query}")')
        print(f"Query vector {_fmt_vec(q, args.dims)}")
        print(f"{'score':>6}  {'chunk id':<42} text")
        for cid, dist in zip(res["ids"][0], res["distances"][0]):
            print(f"{1 - dist:6.3f}  {cid:<42} {_short(by_id.get(cid, {}).get('text', ''), 70)}")
        print()

    # ---- Records -------------------------------------------------------------
    rows = []
    for cid, m, v in zip(ids, metas, vecs):
        if args.id and cid != args.id:
            continue
        if args.scheme and (m["scheme_id"] or "official") != args.scheme:
            continue
        if args.topic and m["topic"] != args.topic:
            continue
        rows.append((cid, m, v))
    if not rows:
        print("No records match those filters.")
        return 1

    if args.csv:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        with args.csv.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["id", "scheme_id", "topic", "kind", "text", "embedded_text"]
                       + [f"d{i}" for i in range(vecs.shape[1])])
            for cid, m, v in rows:
                c = by_id.get(cid, {})
                w.writerow([cid, m["scheme_id"], m["topic"], m["kind"], c.get("text", ""),
                            config.EMBED_DOC_PREFIX + embedder.document_text(c) if c else ""]
                           + [f"{x:.6f}" for x in v])
        print(f"Wrote {len(rows)} records × {vecs.shape[1]} dims -> {args.csv}")
        return 0

    shown = rows if args.limit == 0 else rows[: args.limit]
    for cid, m, v in shown:
        c = by_id.get(cid, {})
        print(f"── {cid}   scheme: {m['scheme_id'] or '(official note)'}   topic: {m['topic']}   kind: {m['kind']}")
        print(f"   text     : {c.get('text', '(not in corpus.json)')}")
        if c:
            print(f"   embedded : {_short(config.EMBED_DOC_PREFIX + embedder.document_text(c), 160)}")
        if args.full:
            print(f"   vector ({len(v)} dims):")
            for i in range(0, len(v), 8):
                print("     " + "  ".join(f"{x:+.5f}" for x in v[i:i + 8]))
        else:
            print(f"   vector   : {_fmt_vec(v, args.dims)}  ({len(v)} dims, norm {np.linalg.norm(v):.4f})")
        print()
    if len(rows) > len(shown):
        print(f"… {len(rows) - len(shown)} more; use --limit 0 for all, or --csv to export.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
