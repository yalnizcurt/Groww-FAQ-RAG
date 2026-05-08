"""Phase 1.6 Indexer — ChromaDB (dense) + rank_bm25 (sparse) + manifest.json.

Atomic-swap pattern: build under data/index/.staging/, then rename to live.
"""

from __future__ import annotations

import hashlib
import json
import logging
import pickle
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from ..config_loader import INDEX_DIR, PROCESSED_DIR, ensure_dirs, load_sources
from .chunker import Chunk
from .embedder import Embedder, persist_embedder_meta

logger = logging.getLogger(__name__)

CHROMA_COLLECTION = "mf_faq"
CHROMA_DIR_NAME = "chroma"
BM25_FILE = "bm25.pkl"
MANIFEST_FILE = "manifest.json"
CHUNKS_FILE = "chunks.jsonl"
STAGING_NAME = ".staging"

_TOKEN_RE = re.compile(r"[A-Za-z0-9\u20b9%.\-]+")


def bm25_tokenize(text: str) -> List[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text or "") if t]


@dataclass
class IndexHandle:
    chroma_client: object
    chroma_collection: object
    bm25: object
    bm25_corpus_tokens: List[List[str]]
    chunks: List[Chunk]
    chunk_by_id: Dict[str, Chunk]
    manifest: Dict
    embedder: Embedder

    @property
    def n_chunks(self) -> int:
        return len(self.chunks)

    def get_dense(self) -> object:
        return self.chroma_collection


def _load_chunks_from_disk() -> List[Chunk]:
    chunks: List[Chunk] = []
    for scheme in load_sources().schemes:
        path = PROCESSED_DIR / scheme.id / "chunks.jsonl"
        if not path.exists():
            logger.warning("[indexer] missing chunks.jsonl for %s", scheme.id)
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            chunks.append(Chunk(**d))
    return chunks


def build_index() -> IndexHandle:
    """Build (or rebuild) the index from chunks on disk. Atomic swap."""
    import chromadb
    from rank_bm25 import BM25Okapi

    ensure_dirs()
    chunks = _load_chunks_from_disk()
    if not chunks:
        raise RuntimeError("No chunks found on disk — run the ingestion pipeline first.")

    embedder = Embedder.get()
    persist_embedder_meta(embedder.model_name, embedder.dim)

    staging = INDEX_DIR / STAGING_NAME
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)

    chroma_dir = staging / CHROMA_DIR_NAME
    chroma_dir.mkdir(exist_ok=True)

    # Build dense index in staging.
    client = chromadb.PersistentClient(path=str(chroma_dir))
    try:
        client.delete_collection(CHROMA_COLLECTION)
    except Exception:
        pass
    collection = client.create_collection(
        name=CHROMA_COLLECTION, metadata={"hnsw:space": "cosine"}
    )

    batch = embedder.embed_documents(chunks)
    metadatas = []
    documents = []
    ids = []
    for c, vec in zip(chunks, batch.vectors):
        ids.append(c.chunk_id)
        documents.append(c.text)
        metadatas.append(
            {
                "scheme_id": c.scheme_id,
                "scheme_name": c.scheme_name,
                "section": c.section,
                "source_url": c.source_url,
                "last_updated": c.last_updated,
                "doc_type": c.doc_type,
                "section_source": c.section_source,
            }
        )
    collection.add(
        ids=ids,
        embeddings=batch.vectors.tolist(),
        metadatas=metadatas,
        documents=documents,
    )

    # Build sparse BM25.
    bm25_tokens = [bm25_tokenize(c.text) for c in chunks]
    bm25 = BM25Okapi(bm25_tokens)
    with (staging / BM25_FILE).open("wb") as fh:
        pickle.dump(
            {"chunk_ids": [c.chunk_id for c in chunks], "tokens": bm25_tokens},
            fh,
        )

    # Persist canonical chunk store.
    with (staging / CHUNKS_FILE).open("w", encoding="utf-8") as fh:
        for c in chunks:
            fh.write(json.dumps(c.to_dict(), ensure_ascii=False) + "\n")

    # Manifest.
    cfg = load_sources()
    per_scheme: Dict[str, int] = {}
    for c in chunks:
        per_scheme[c.scheme_id] = per_scheme.get(c.scheme_id, 0) + 1
    source_hashes = {}
    for s in cfg.schemes:
        cleaned = PROCESSED_DIR / s.id / "cleaned.json"
        if cleaned.exists():
            try:
                source_hashes[s.id] = json.loads(
                    cleaned.read_text(encoding="utf-8")
                ).get("stable_content_hash")
            except Exception:
                source_hashes[s.id] = None
    manifest = {
        "built_at": datetime.now(timezone.utc).isoformat(),
        "embedder": {"model": batch.model, "dim": batch.dim},
        "n_chunks": len(chunks),
        "per_scheme_counts": per_scheme,
        "source_hashes": source_hashes,
        "whitelist_urls": list(cfg.urls),
    }
    (staging / MANIFEST_FILE).write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )

    # Atomic swap: replace live index with staging.
    live_chroma = INDEX_DIR / CHROMA_DIR_NAME
    live_bm25 = INDEX_DIR / BM25_FILE
    live_chunks = INDEX_DIR / CHUNKS_FILE
    live_manifest = INDEX_DIR / MANIFEST_FILE
    if live_chroma.exists():
        shutil.rmtree(live_chroma)
    shutil.move(str(staging / CHROMA_DIR_NAME), str(live_chroma))
    shutil.move(str(staging / BM25_FILE), str(live_bm25))
    shutil.move(str(staging / CHUNKS_FILE), str(live_chunks))
    shutil.move(str(staging / MANIFEST_FILE), str(live_manifest))
    shutil.rmtree(staging)

    logger.info(
        "[indexer] built index n_chunks=%d schemes=%d", len(chunks), len(per_scheme)
    )
    return load_index()


_loaded_handle: Optional[IndexHandle] = None


def load_index(force: bool = False) -> IndexHandle:
    """Load the live index from disk (idempotent, cached)."""
    global _loaded_handle
    if _loaded_handle is not None and not force:
        return _loaded_handle

    import chromadb
    from rank_bm25 import BM25Okapi

    chroma_dir = INDEX_DIR / CHROMA_DIR_NAME
    bm25_path = INDEX_DIR / BM25_FILE
    chunks_path = INDEX_DIR / CHUNKS_FILE
    manifest_path = INDEX_DIR / MANIFEST_FILE

    if not (
        chroma_dir.exists()
        and bm25_path.exists()
        and chunks_path.exists()
        and manifest_path.exists()
    ):
        raise RuntimeError(
            "index not built; run build_index() first (data/index/* missing)"
        )

    chunks: List[Chunk] = []
    for line in chunks_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        chunks.append(Chunk(**d))

    chunk_by_id = {c.chunk_id: c for c in chunks}

    client = chromadb.PersistentClient(path=str(chroma_dir))
    collection = client.get_collection(CHROMA_COLLECTION)

    with bm25_path.open("rb") as fh:
        sp = pickle.load(fh)
    bm25 = BM25Okapi(sp["tokens"])

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    embedder = Embedder.get(manifest["embedder"]["model"])

    _loaded_handle = IndexHandle(
        chroma_client=client,
        chroma_collection=collection,
        bm25=bm25,
        bm25_corpus_tokens=sp["tokens"],
        chunks=chunks,
        chunk_by_id=chunk_by_id,
        manifest=manifest,
        embedder=embedder,
    )
    logger.info("[indexer] loaded index n_chunks=%d", len(chunks))
    return _loaded_handle


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    h = build_index()
    print(f"built index: {h.n_chunks} chunks across {len(h.manifest['per_scheme_counts'])} schemes")
