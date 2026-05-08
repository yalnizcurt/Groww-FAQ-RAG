"""Hybrid retrieval — ChromaDB dense + BM25 sparse + RRF fusion + section-hint boost."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

from ..ingestion.chunker import Chunk
from ..ingestion.indexer import IndexHandle, bm25_tokenize, load_index
from .normalizer import normalize
from .scheme_resolver import SchemeMatch, resolve

logger = logging.getLogger(__name__)

# Section-hint mapping: keywords in query → boosted section names.
SECTION_HINTS: Dict[str, Tuple[str, ...]] = {
    "exit load": ("Exit Load and Tax",),
    "tax": ("Exit Load and Tax",),
    "taxation": ("Exit Load and Tax",),
    "capital gain": ("Exit Load and Tax",),
    "lock-in": ("Exit Load and Tax", "Fund Details"),
    "lockin": ("Exit Load and Tax", "Fund Details"),
    "expense ratio": ("Fund Details",),
    "expense": ("Fund Details",),
    "er": ("Fund Details",),
    "aum": ("Fund Details",),
    "fund size": ("Fund Details",),
    "sip": ("Minimum Investments",),
    "minimum investment": ("Minimum Investments",),
    "minimum sip": ("Minimum Investments",),
    "min sip": ("Minimum Investments",),
    "lump sum": ("Minimum Investments",),
    "lumpsum": ("Minimum Investments",),
    "riskometer": ("Riskometer", "Fund Details"),
    "risk": ("Riskometer", "Fund Details"),
    "benchmark": ("Fund Details", "About"),
    "manager": ("Fund Manager",),
    "fund house": ("Fund House",),
    "amc": ("Fund House",),
    "about": ("About",),
    "objective": ("About",),
}


@dataclass
class RetrievedChunk:
    chunk: Chunk
    score: float
    dense_rank: Optional[int] = None
    sparse_rank: Optional[int] = None
    section_boost: float = 0.0


def _section_hint_for_query(query_norm: str) -> Tuple[str, ...]:
    matches: List[str] = []
    for k, sections in SECTION_HINTS.items():
        if k in query_norm:
            matches.extend(sections)
    # Dedup but preserve order.
    seen = set()
    out: List[str] = []
    for s in matches:
        if s not in seen:
            out.append(s)
            seen.add(s)
    return tuple(out)


_NUMERIC_RE = re.compile(r"[0-9]+(?:[.,][0-9]+)?(?:%|cr|crore|years?|months?)?")


def _is_numeric_heavy(query: str) -> bool:
    return bool(_NUMERIC_RE.search(query)) or any(
        ch in query for ch in ("\u20b9", "%")
    )


class HybridRetriever:
    def __init__(self, index: Optional[IndexHandle] = None):
        self.index = index or load_index()

    def search(
        self,
        query: str,
        top_k: int = 10,
        scheme_filter: Optional[str] = None,
        section_hint: Optional[Tuple[str, ...]] = None,
        sparse_weight: float = 0.5,
        auto_resolve_scheme: bool = True,
    ) -> List[RetrievedChunk]:
        if not query.strip():
            return []
        idx = self.index
        norm = normalize(query)
        bm25_query_tokens = bm25_tokenize(norm) or bm25_tokenize(query)
        if section_hint is None:
            section_hint = _section_hint_for_query(norm)
        if _is_numeric_heavy(query):
            sparse_weight = 0.65  # bump sparse for exact-fact queries

        # Dense search via Chroma.
        scheme_match = resolve(query)
        scheme_name_hint = scheme_match.scheme.name if scheme_match else ""
        # Auto-apply scheme filter when resolver finds a confident match.
        if auto_resolve_scheme and scheme_filter is None and scheme_match is not None:
            scheme_filter = scheme_match.scheme.id
        qvec = idx.embedder.embed_query(query, scheme_name_hint=scheme_name_hint)
        where = None
        if scheme_filter:
            where = {"scheme_id": scheme_filter}
        n_dense = min(20, idx.n_chunks)
        dense_res = idx.chroma_collection.query(
            query_embeddings=[qvec.tolist()],
            n_results=n_dense,
            where=where,
        )
        dense_ids: List[str] = (dense_res.get("ids") or [[]])[0]
        dense_distances = (dense_res.get("distances") or [[]])[0]
        # Convert cosine distance → score; we mostly need ordering.
        dense_scores = {cid: 1.0 - float(d) for cid, d in zip(dense_ids, dense_distances)}

        if not dense_ids and where is not None:
            # Relax scheme filter once if it removed everything.
            logger.info("[hybrid] scheme filter %s left no candidates; relaxing", scheme_filter)
            dense_res = idx.chroma_collection.query(
                query_embeddings=[qvec.tolist()],
                n_results=n_dense,
            )
            dense_ids = (dense_res.get("ids") or [[]])[0]
            dense_distances = (dense_res.get("distances") or [[]])[0]
            dense_scores = {cid: 1.0 - float(d) for cid, d in zip(dense_ids, dense_distances)}

        # Sparse search via BM25.
        bm25_scores = idx.bm25.get_scores(bm25_query_tokens)
        # Map back to chunk_ids (BM25 was built in chunks order).
        chunk_ids_in_order = [c.chunk_id for c in idx.chunks]
        ranked_sparse = sorted(
            zip(chunk_ids_in_order, bm25_scores), key=lambda x: x[1], reverse=True
        )
        if scheme_filter:
            ranked_sparse = [
                (cid, s) for cid, s in ranked_sparse if idx.chunk_by_id[cid].scheme_id == scheme_filter
            ] or ranked_sparse  # relax if empty
        sparse_top = ranked_sparse[: min(20, len(ranked_sparse))]
        sparse_scores = {cid: float(s) for cid, s in sparse_top}

        # RRF fusion.
        K = 60
        fused: Dict[str, float] = {}
        for rank, cid in enumerate(dense_ids, start=1):
            fused[cid] = fused.get(cid, 0.0) + (1.0 - sparse_weight) * (1.0 / (K + rank))
        for rank, (cid, _) in enumerate(sparse_top, start=1):
            fused[cid] = fused.get(cid, 0.0) + sparse_weight * (1.0 / (K + rank))

        # Section-hint boost.
        results: List[RetrievedChunk] = []
        for cid, sc in fused.items():
            ch = idx.chunk_by_id.get(cid)
            if ch is None:
                continue
            boost = 0.0
            if section_hint and ch.section in section_hint:
                # Strong boost on RRF scores so the section actually wins.
                boost = 0.05
            results.append(
                RetrievedChunk(
                    chunk=ch,
                    score=sc + boost,
                    section_boost=boost,
                )
            )
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_k]
