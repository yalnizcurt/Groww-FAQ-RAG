"""Cross-encoder reranker — BAAI/bge-reranker-base over the hybrid top-K.

Gracefully degrades to no-op if the reranker model can't be downloaded.
"""

from __future__ import annotations

import logging
import os
from typing import List, Optional

from .hybrid import RetrievedChunk

logger = logging.getLogger(__name__)

RERANKER_MODEL = os.environ.get("RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")


class Reranker:
    _instance: "Reranker | None" = None

    @classmethod
    def get(cls) -> "Reranker":
        if cls._instance is None:
            cls._instance = Reranker()
        return cls._instance

    def __init__(self):
        self._model = None
        self._load_attempted = False

    def _load(self):
        if self._load_attempted:
            return
        self._load_attempted = True
        try:
            from sentence_transformers import CrossEncoder

            logger.info("[reranker] loading %s", RERANKER_MODEL)
            self._model = CrossEncoder(RERANKER_MODEL)
            logger.info("[reranker] loaded")
        except Exception as exc:
            logger.warning("[reranker] failed to load %s: %s. Falling back to no-op.", RERANKER_MODEL, exc)
            self._model = None

    def rerank(self, query: str, hits: List[RetrievedChunk], top_k: int = 3) -> List[RetrievedChunk]:
        if not hits:
            return []
        self._load()
        if self._model is None:
            return hits[:top_k]
        pairs = [(query, h.chunk.text) for h in hits]
        try:
            scores = self._model.predict(pairs, show_progress_bar=False)
        except Exception as exc:
            logger.warning("[reranker] predict failed: %s; falling back", exc)
            return hits[:top_k]
        # Cross-encoder logits range ~ -10..+10. Section-hint boost should be
        # large enough to overcome a marginal model preference (e.g. choosing
        # the marketing About blurb over the Fund Details widget for an
        # "expense ratio" query).
        SECTION_BOOST_AMP = 30.0
        for h, sc in zip(hits, scores):
            h.score = float(sc) + h.section_boost * SECTION_BOOST_AMP
        hits.sort(key=lambda r: r.score, reverse=True)
        return hits[:top_k]


def confidence_margin(reranked: List[RetrievedChunk]) -> float:
    """Top - second margin; small → low confidence."""
    if len(reranked) < 2:
        return float(reranked[0].score) if reranked else 0.0
    return float(reranked[0].score) - float(reranked[1].score)
