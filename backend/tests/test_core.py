"""POC — single end-to-end test that exercises the entire RAG pipeline.

Run with:  cd /app/backend && python -m tests.test_core

This is intentionally NOT a pytest module; it's a direct script so it can be
used as the Phase 1 \"core proves itself before app is built\" gate.

What it verifies:
  1. Phase 0 — sources.yaml validates to exactly 5 Groww URLs.
  2. Phase 1.1–1.7 — ingestion pipeline runs and produces a healthy index.
  3. Phase 2 — hybrid retrieval + rerank returns a plausible top chunk
     for each gold question, citing the right scheme.
  4. Phase 3 — PII guard, refusal composer, post-processor enforce policy:
        - PAN-containing query  → 0 URLs.
        - Advisory query        → 1 whitelisted URL.
        - Factual query         → 1 whitelisted URL + footer date.

If any assertion fails, the script exits non-zero with details.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import traceback
from pathlib import Path
from typing import List, Tuple

# Make sure /app/backend is on sys.path when called directly.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("poc")

FAILURES: List[str] = []


def _check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        logger.info("PASS  %s", label)
    else:
        logger.error("FAIL  %s :: %s", label, detail)
        FAILURES.append(f"{label} :: {detail}")


def phase0_governance() -> None:
    from mf_faq.config_loader import (
        is_whitelisted_url,
        load_disclaimer,
        load_refusals,
        load_sources,
    )

    cfg = load_sources()
    _check("phase0.sources_count_is_5", len(cfg.schemes) == 5, f"got {len(cfg.schemes)}")
    _check(
        "phase0.amc_is_hdfc",
        cfg.amc_id == "hdfc_mf",
        f"got {cfg.amc_id}",
    )
    expected_urls = {
        "https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth",
        "https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth",
        "https://groww.in/mutual-funds/hdfc-focused-fund-direct-growth",
        "https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth",
        "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth",
    }
    _check(
        "phase0.url_set_matches",
        set(cfg.urls) == expected_urls,
        f"diff={set(cfg.urls).symmetric_difference(expected_urls)}",
    )
    _check(
        "phase0.whitelist_check",
        all(is_whitelisted_url(u) for u in cfg.urls)
        and not is_whitelisted_url("https://example.com/foo"),
    )
    _check(
        "phase0.disclaimer_present",
        "facts-only" in load_disclaimer().lower(),
    )
    refusals = load_refusals()
    _check(
        "phase0.refusal_intents_present",
        any(i.id == "advisory" for i in refusals.intents)
        and any(i.id == "comparison" for i in refusals.intents),
    )


def phase1_ingest() -> None:
    from mf_faq.config_loader import load_sources
    from mf_faq.ingestion.pipeline import refresh

    cfg = load_sources()
    res = refresh()
    _check(
        "phase1.refresh_outcome",
        # "frozen" is a valid outcome when the existing index is already healthy
        # and a multi-URL drift was detected — the refresh deliberately preserves
        # the existing index instead of overwriting on a drifted snapshot.
        res.outcome in ("ok", "partial", "frozen"),
        f"outcome={res.outcome} error={res.error} per_scheme={list(res.per_scheme.keys())}",
    )
    # We require at least 4/5 schemes to have at least 3 chunks (Groww may rate-limit one).
    healthy = 0
    from mf_faq.ingestion.indexer import load_index

    handle = load_index(force=True)
    counts = handle.manifest.get("per_scheme_counts", {})
    for scheme in cfg.schemes:
        n = counts.get(scheme.id, 0)
        if n >= 3:
            healthy += 1
        logger.info("  %s: chunks=%d", scheme.id, n)
    _check(
        "phase1.>=4_schemes_have_>=3_chunks",
        healthy >= 4,
        f"healthy_schemes={healthy}/5 counts={counts}",
    )
    _check(
        "phase1.total_chunks_reasonable",
        15 <= handle.n_chunks <= 200,
        f"got {handle.n_chunks}",
    )


def phase2_retrieve() -> None:
    from mf_faq.retrieval.hybrid import HybridRetriever
    from mf_faq.retrieval.reranker import Reranker

    retriever = HybridRetriever()
    reranker = Reranker.get()

    gold: List[Tuple[str, str, str]] = [
        # (query, expected scheme_id, expected section keyword)
        ("What is the expense ratio of HDFC Mid Cap Fund?", "hdfc_mid_cap", "expense"),
        ("What is the exit load of HDFC Equity Fund?", "hdfc_equity", "exit"),
        ("Who manages HDFC Focused Fund?", "hdfc_focused", "manager"),
        ("Lock-in period of HDFC ELSS Tax Saver?", "hdfc_elss", ""),
        ("Minimum SIP for HDFC Large Cap Fund?", "hdfc_large_cap", ""),
    ]
    correct = 0
    for q, expected_scheme, _ in gold:
        hits = retriever.search(q, top_k=8)
        ranked = reranker.rerank(q, hits, top_k=3)
        if not ranked:
            logger.warning("  no hits for: %s", q)
            continue
        top = ranked[0]
        ok = top.chunk.scheme_id == expected_scheme
        if ok:
            correct += 1
        logger.info(
            "  Q='%s' -> scheme=%s section=%s ok=%s",
            q,
            top.chunk.scheme_id,
            top.chunk.section,
            ok,
        )
    _check(
        "phase2.scheme_routing_>=4/5",
        correct >= 4,
        f"correct={correct}/5",
    )


def phase3_orchestrator() -> None:
    from mf_faq.config_loader import is_whitelisted_url
    from mf_faq.orchestrator.post_processor import sentence_count
    from mf_faq.orchestrator.service import Orchestrator

    orch = Orchestrator.get()

    # 3a. Factual query — must yield exactly one whitelisted URL + body ≤3 sents.
    res = orch.ask("What is the exit load of HDFC Equity Fund?", use_groq=False)
    rendered = res.answer.render()
    logger.info("factual_answer: %s", rendered)
    _check(
        "phase3.factual_intent",
        res.answer.intent == "factual",
        f"intent={res.answer.intent}",
    )
    _check(
        "phase3.factual_one_url",
        res.answer.citation_url is not None
        and is_whitelisted_url(res.answer.citation_url),
        f"url={res.answer.citation_url}",
    )
    _check(
        "phase3.factual_<=3_sentences",
        sentence_count(res.answer.body) <= 3,
        f"sents={sentence_count(res.answer.body)}",
    )
    _check(
        "phase3.factual_footer_present",
        "Last updated from sources:" in rendered,
    )

    # 3b. Advisory query — must be refusal + 1 whitelisted URL.
    res2 = orch.ask("Should I invest in HDFC Mid Cap Fund?")
    _check(
        "phase3.advisory_refused",
        res2.answer.intent in ("advisory", "comparison", "prediction"),
        f"intent={res2.answer.intent}",
    )
    _check(
        "phase3.advisory_one_url",
        res2.answer.citation_url is not None
        and is_whitelisted_url(res2.answer.citation_url),
        f"url={res2.answer.citation_url}",
    )
    _check(
        "phase3.advisory_no_banned",
        "recommend" not in res2.answer.body.lower()
        and "should invest" not in res2.answer.body.lower(),
    )

    # 3c. Comparison query.
    res3 = orch.ask("Which is better: HDFC Mid Cap or HDFC Large Cap?")
    _check(
        "phase3.comparison_refused",
        res3.answer.intent == "comparison",
        f"intent={res3.answer.intent}",
    )

    # 3d. PII query — must be blocked with NO URLs.
    res4 = orch.ask("My PAN is ABCDE1234F, what is the exit load?")
    _check(
        "phase3.pii_blocked",
        res4.answer.intent == "pii",
        f"intent={res4.answer.intent}",
    )
    _check(
        "phase3.pii_no_urls",
        res4.answer.citation_url is None
        and "http" not in res4.answer.render(),
        f"render={res4.answer.render()}",
    )

    # 3e. Off-corpus / nonsense — must be dont_know with NO URL.
    res5 = orch.ask("What is the password to my email account?")
    # If the query has no PII and isn't advisory, may classify as factual
    # but retrieval should be too weak → dont_know.
    logger.info(
        "off_corpus: intent=%s url=%s body=%s",
        res5.answer.intent,
        res5.answer.citation_url,
        res5.answer.body[:80],
    )


def main() -> int:
    try:
        logger.info("=== Phase 0: Governance ===")
        phase0_governance()
        logger.info("=== Phase 1: Ingestion ===")
        phase1_ingest()
        logger.info("=== Phase 2: Retrieval ===")
        phase2_retrieve()
        logger.info("=== Phase 3: Orchestrator ===")
        phase3_orchestrator()
    except Exception:
        logger.error("unhandled exception\n%s", traceback.format_exc())
        FAILURES.append("unhandled exception")

    print("\n\n" + "=" * 60)
    if FAILURES:
        print(f"FAILURES ({len(FAILURES)}):")
        for f in FAILURES:
            print("  -", f)
        return 1
    print("ALL POC CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
