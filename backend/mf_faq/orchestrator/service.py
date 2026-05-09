"""Orchestrator service — conversational, memory-aware, compliance-safe.

Flow:
  1. Session context  → load/create session, infer scheme from history.
  2. PII guard        → if hit, return pii_block (no URL).
  3. Intent classify  → greeting/conversational/advisory/comparison/prediction → early return.
  4. Query expansion  → resolve scheme (from query or memory), detect metric.
  5. Hybrid retrieve  → Phase 2 retriever with scheme filter.
  6. Cross-encoder    → rerank top-1.
  7. Confidence gate  → below threshold → graceful fallback.
  8. Generator        → Groq (warm tone) or extractive.
  9. Post-processor   → enforce compliance, generate suggestions.
  10. Record to memory → update session context.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ..config_loader import load_sources
from ..ingestion.indexer import IndexHandle, load_index
from ..retrieval.hybrid import HybridRetriever, RetrievedChunk
from ..retrieval.reranker import Reranker, confidence_margin
from ..retrieval.scheme_resolver import resolve
from .generator import generate_body
from .semantic_router import parse_query_semantically
from .memory import SessionContext, detect_metric, get_session
from .pii_guard import detect_pii
from .post_processor import (
    FinalAnswer,
    build_conversational_ack,
    build_dont_know,
    build_factual,
    build_greeting,
    build_pii_block,
    build_refusal,
)
from .refusal import compose_refusal

logger = logging.getLogger(__name__)

DEFAULT_CONF_THRESHOLD = float(os.environ.get("CONF_THRESHOLD", "-9.0"))
DEFAULT_MARGIN_THRESHOLD = float(os.environ.get("MARGIN_THRESHOLD", "0.5"))


@dataclass
class AskResult:
    answer: FinalAnswer
    request_id: str
    intent: str
    used_groq: bool
    latency_ms: int
    top_chunks: List[Dict[str, Any]]
    scheme_id: Optional[str]
    margin: float
    suggestions: List[str]


class Orchestrator:
    """Singleton orchestrator with session memory and conversational logic."""

    _instance: "Orchestrator | None" = None

    @classmethod
    def get(cls) -> "Orchestrator":
        if cls._instance is None:
            cls._instance = Orchestrator()
        return cls._instance

    def __init__(self):
        self._index: Optional[IndexHandle] = None
        self._retriever: Optional[HybridRetriever] = None
        self._reranker: Optional[Reranker] = None

    def _ensure_loaded(self):
        if self._index is None:
            self._index = load_index()
        if self._retriever is None:
            self._retriever = HybridRetriever(self._index)
        if self._reranker is None:
            self._reranker = Reranker.get()

    def reload(self):
        self._index = None
        self._retriever = None

    def _make_result(
        self,
        ans: FinalAnswer,
        request_id: str,
        intent: str,
        t0: float,
        used_groq: bool = False,
        top_chunks: Optional[List[Dict[str, Any]]] = None,
        scheme_id: Optional[str] = None,
        margin: float = 0.0,
    ) -> AskResult:
        return AskResult(
            answer=ans,
            request_id=request_id,
            intent=intent,
            used_groq=used_groq,
            latency_ms=int((time.time() - t0) * 1000),
            top_chunks=top_chunks or [],
            scheme_id=scheme_id or ans.scheme_id,
            margin=margin,
            suggestions=ans.suggestions,
        )

    def ask(
        self,
        query: str,
        session_id: Optional[str] = None,
        use_groq: Optional[bool] = None,
    ) -> AskResult:
        request_id = str(uuid.uuid4())
        t0 = time.time()

        # --- 1. Session context ---
        sid = session_id or "default"
        ctx = get_session(sid)
        metric = detect_metric(query or "")

        # --- 2. PII guard ---
        pii_hits = detect_pii(query or "")
        if pii_hits:
            ans = build_pii_block()
            ctx.record(query or "", None, None, None, "pii")
            return self._make_result(ans, request_id, "pii", t0)

        # --- 2b. Fast regex safety net (catches obvious unsafe queries before LLM) ---
        fast_refusal = _fast_safety_check(query or "")
        if fast_refusal:
            ref = compose_refusal(query or "", fast_refusal)
            ans = build_refusal(
                body=ref.body,
                citation_url=ref.educational_url,
                intent_id=ref.intent_id,
                scheme_id=ref.scheme_id,
                scheme_name=_scheme_name_for(ref.scheme_id),
            )
            ctx.record(query or "", ref.scheme_id, _scheme_name_for(ref.scheme_id), None, fast_refusal)
            return self._make_result(ans, request_id, fast_refusal, t0,
                                     scheme_id=ref.scheme_id)

        # --- 3. Semantic Query Understanding ---
        sem_intent = parse_query_semantically(
            query or "", 
            last_scheme_name=ctx.last_scheme_name, 
            last_topic=ctx.last_metric
        )
        
        # Override metric with LLM's inferred metric if it found one
        if sem_intent.metric:
            metric = sem_intent.metric

        if sem_intent.is_pii:
            ans = build_pii_block()
            ctx.record(query or "", None, None, None, "pii")
            return self._make_result(ans, request_id, "pii", t0)

        if sem_intent.is_greeting:
            ans = build_greeting()
            ctx.record(query or "", None, None, None, "greeting")
            return self._make_result(ans, request_id, "greeting", t0)

        if sem_intent.is_conversational:
            ans = build_conversational_ack(
                scheme_id=ctx.last_scheme_id,
                scheme_name=ctx.last_scheme_name,
                last_metric=ctx.last_metric,
            )
            ctx.record(query or "", ctx.last_scheme_id, ctx.last_scheme_name, None, "conversational")
            return self._make_result(ans, request_id, "conversational", t0,
                                     scheme_id=ctx.last_scheme_id)

        # --- 3b. Compliance Router (runs BEFORE clarification gate — safety first) ---
        if sem_intent.is_performance_query or sem_intent.is_comparison or sem_intent.is_advisory:
            if sem_intent.is_performance_query:
                ref_intent_id = "prediction"
            elif sem_intent.is_comparison:
                ref_intent_id = "comparison"
            else:
                ref_intent_id = "advisory"
                
            ref = compose_refusal(query or "", ref_intent_id)
            ans = build_refusal(
                body=ref.body,
                citation_url=ref.educational_url,
                intent_id=ref.intent_id,
                scheme_id=ref.scheme_id,
                scheme_name=_scheme_name_for(ref.scheme_id),
            )
            ctx.record(query or "", ref.scheme_id, _scheme_name_for(ref.scheme_id), None, ref_intent_id)
            return self._make_result(ans, request_id, ref_intent_id, t0,
                                     scheme_id=ref.scheme_id)

        # --- 4. Clarification Gate (only reached for non-compliance queries) ---
        if sem_intent.needs_clarification or sem_intent.confidence < 0.6 or sem_intent.capability == "out_of_domain":
            ans = build_dont_know(
                scheme_id=ctx.last_scheme_id,
                scheme_name=ctx.last_scheme_name,
            )
            ctx.record(query or "", None, None, None, "dont_know")
            return self._make_result(ans, request_id, "dont_know", t0)

        # --- 4. Query expansion: resolve scheme from query, parser, or memory ---
        sm = resolve(query or "")
        if sm:
            scheme_id = sm.scheme.id
            scheme_name = sm.scheme.name
        elif sem_intent.scheme_name and resolve(sem_intent.scheme_name):
            sm_parser = resolve(sem_intent.scheme_name)
            scheme_id = sm_parser.scheme.id
            scheme_name = sm_parser.scheme.name
            logger.info("[orchestrator] inferred scheme=%s from LLM parser", scheme_id)
        elif ctx.has_context:
            scheme_id = ctx.last_scheme_id
            scheme_name = ctx.last_scheme_name
            logger.info(
                "[orchestrator] inferred scheme=%s from session context", scheme_id
            )
        else:
            scheme_id = None
            scheme_name = None

        # --- 5+6. Retrieve + rerank ---
        try:
            self._ensure_loaded()
        except Exception as exc:
            logger.exception("[orchestrator] index not ready: %s", exc)
            ans = build_dont_know(scheme_id, scheme_name)
            ctx.record(query or "", scheme_id, scheme_name, metric, "dont_know")
            return self._make_result(ans, request_id, "dont_know", t0, scheme_id=scheme_id)

        # Enrich query for retrieval when scheme was inferred from context.
        # This gives the embedder better semantic signal.
        retrieval_query = query or ""
        if scheme_name and not sm:
            # Scheme was inferred from context, not in the original query.
            short = scheme_name.replace(" - Direct Growth", "").replace(" - Direct Plan Growth", "")
            retrieval_query = f"{short} {retrieval_query}"
        # Also expand metric synonyms for better chunk matching.
        if metric:
            retrieval_query = f"{metric} {retrieval_query}"

        hits = self._retriever.search(
            query=retrieval_query,
            top_k=10,
            scheme_filter=scheme_id,
        )
        if not hits:
            ans = build_dont_know(scheme_id, scheme_name)
            ctx.record(query or "", scheme_id, scheme_name, metric, "dont_know")
            return self._make_result(ans, request_id, "dont_know", t0, scheme_id=scheme_id)

        reranked = self._reranker.rerank(retrieval_query, hits, top_k=3)
        margin = confidence_margin(reranked)
        top = reranked[0]

        # --- 7. Confidence & Semantic Validation gate ---
        # Field-level validation: Ensure the retrieved chunk section matches the capability/metric.
        SECTION_MAP = {
            "fund_costs": ["Exit Load and Tax", "Fund Details"],
            "fund_risk": ["Riskometer", "Fund Details", "About"],
            "minimum_investment": ["Minimum Investments", "Fund Details"],
            "fund_management": ["Fund Manager", "Fund Details", "About"],
            "portfolio": ["Portfolio", "Holdings", "Fund Details"],
        }
        validation_failed = False
        allowed = SECTION_MAP.get(sem_intent.capability)
        if allowed and top.chunk.section not in allowed:
            validation_failed = True
        
        if top.score < DEFAULT_CONF_THRESHOLD and margin < DEFAULT_MARGIN_THRESHOLD:
            logger.info("[orchestrator] low confidence top=%.3f (margin=%.3f)", top.score, margin)
            validation_failed = True
            
        if validation_failed:
            logger.info("[orchestrator] retrieval validation failed (capability=%s, metric=%s, section=%s)", 
                        sem_intent.capability, sem_intent.metric, top.chunk.section)
            ans = build_dont_know(top.chunk.scheme_id, top.chunk.scheme_name)
            ctx.record(query or "", top.chunk.scheme_id, top.chunk.scheme_name, metric, "dont_know")
            return self._make_result(
                ans, request_id, "dont_know", t0,
                top_chunks=_to_dict(reranked),
                scheme_id=top.chunk.scheme_id,
                margin=margin,
            )

        # --- 8. Generate body ---
        gen = generate_body(query or "", top, use_groq=use_groq, extra_chunks=reranked[1:])

        # --- 9. Post-process ---
        ans = build_factual(
            body=gen.body,
            citation_url=top.chunk.source_url,
            last_updated=top.chunk.last_updated or None,
            chunk_ids=[r.chunk.chunk_id for r in reranked],
            confidence=float(top.score),
            scheme_id=top.chunk.scheme_id,
            scheme_name=top.chunk.scheme_name,
            last_metric=metric,
        )

        # --- 10. Record to memory ---
        ctx.record(
            query or "",
            top.chunk.scheme_id,
            top.chunk.scheme_name,
            metric,
            ans.intent,
        )

        if not ans.post_check_passed:
            logger.info("[orchestrator] post-check failed; falling back to dont_know")

        return self._make_result(
            ans, request_id, ans.intent, t0,
            used_groq=gen.used_groq,
            top_chunks=_to_dict(reranked),
            scheme_id=top.chunk.scheme_id,
            margin=margin,
        )


def _scheme_name_for(scheme_id: Optional[str]) -> Optional[str]:
    if not scheme_id:
        return None
    cfg = load_sources()
    s = cfg.get_scheme(scheme_id)
    return s.name if s else None


def _to_dict(hits: List[RetrievedChunk]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for h in hits:
        out.append(
            {
                "chunk_id": h.chunk.chunk_id,
                "scheme_id": h.chunk.scheme_id,
                "section": h.chunk.section,
                "score": float(h.score),
                "source_url": h.chunk.source_url,
                "text": h.chunk.text[:240],
            }
        )
    return out


def hash_query_for_logs(query: str) -> str:
    return "sha256:" + hashlib.sha256((query or "").encode("utf-8")).hexdigest()[:16]


def _fast_safety_check(query: str) -> Optional[str]:
    """Deterministic regex safety net — catches obvious performance, advisory,
    and comparison queries BEFORE the LLM router runs.
    
    Returns the refusal intent_id ('prediction', 'advisory', 'comparison') or None.
    Uses patterns from refusal_intents.yaml for consistency.
    """
    from ..config_loader import load_refusals
    cfg = load_refusals()
    q = query.lower().strip()
    if not q:
        return None
    for intent_cfg in cfg.intents:
        for pattern in intent_cfg.patterns:
            if pattern.lower() in q:
                return intent_cfg.id
    return None
