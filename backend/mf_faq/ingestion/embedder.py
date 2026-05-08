"""Phase 1.5 Embedder — BAAI/bge-small-en-v1.5 via sentence-transformers (384-dim).

We prepend f\"{scheme_name}\\n\\n{text}\" before embedding so near-duplicate boilerplate
across schemes vectors apart (per architecture EC-1.8). The chunk text on disk is
NOT mutated.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence

import numpy as np

from ..config_loader import INDEX_DIR, ensure_dirs
from .chunker import Chunk

logger = logging.getLogger(__name__)

DEFAULT_MODEL = os.environ.get("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")


@dataclass
class EmbeddingBatch:
    chunk_ids: List[str]
    vectors: np.ndarray  # shape (N, dim), float32
    model: str
    dim: int


class Embedder:
    """Lazy-loaded sentence-transformers embedder."""

    _instance: "Embedder | None" = None

    @classmethod
    def get(cls, model_name: str = DEFAULT_MODEL) -> "Embedder":
        if cls._instance is None or cls._instance.model_name != model_name:
            cls._instance = Embedder(model_name)
        return cls._instance

    def __init__(self, model_name: str = DEFAULT_MODEL):
        from sentence_transformers import SentenceTransformer

        logger.info("[embedder] loading model %s", model_name)
        self.model_name = model_name
        self.model = SentenceTransformer(model_name)
        # Probe dim once.
        sample = self.model.encode(["probe"], normalize_embeddings=True)
        self.dim = int(sample.shape[1])
        logger.info("[embedder] model loaded dim=%d", self.dim)

    def embed_documents(self, chunks: Sequence[Chunk]) -> EmbeddingBatch:
        texts = [f"{c.scheme_name}\n\n{c.text}" for c in chunks]
        vectors = self.model.encode(
            texts,
            batch_size=16,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        ).astype(np.float32)
        return EmbeddingBatch(
            chunk_ids=[c.chunk_id for c in chunks],
            vectors=vectors,
            model=self.model_name,
            dim=self.dim,
        )

    def embed_query(self, query: str, scheme_name_hint: str = "") -> np.ndarray:
        text = f"{scheme_name_hint}\n\n{query}".strip() if scheme_name_hint else query
        vec = self.model.encode(
            [text],
            batch_size=1,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )[0]
        return vec.astype(np.float32)


def persist_embedder_meta(model: str, dim: int) -> Path:
    ensure_dirs()
    path = INDEX_DIR / "embedder.json"
    path.write_text(
        json.dumps({"model": model, "dim": dim}, indent=2),
        encoding="utf-8",
    )
    return path


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    e = Embedder.get()
    print(f"loaded {e.model_name} dim={e.dim}")
    persist_embedder_meta(e.model_name, e.dim)
