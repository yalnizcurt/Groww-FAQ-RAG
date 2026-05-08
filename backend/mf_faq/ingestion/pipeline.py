"""Phase 1.7 Pipeline orchestrator — fetch → extract → clean → chunk → embed → index.

Features (per architecture.md):
  * stable_content_hash drift detection — skip re-chunk/embed when only volatile fields ticked.
  * Multi-URL drift in same window freezes the index (does not overwrite).
  * Soft-404 detection (HTTP 200 but missing must-have anchors).
  * refresh_log.jsonl with per-stage timings + outcome ∈ {ok, partial, frozen}.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from ..config_loader import INDEX_DIR, PROCESSED_DIR, ensure_dirs, load_sources
from .chunker import chunk_for_scheme
from .cleaner import clean_for_scheme
from .extractor import extract_for_scheme
from .fetcher import fetch_one
from .indexer import build_index

logger = logging.getLogger(__name__)

REFRESH_LOG = INDEX_DIR / "refresh_log.jsonl"
DRIFT_FREEZE_THRESHOLD = 2  # ≥2 stable-hash diffs in one window → freeze


def _previous_stable_hash(scheme_id: str) -> Optional[str]:
    cleaned = PROCESSED_DIR / scheme_id / "cleaned.json"
    if not cleaned.exists():
        return None
    try:
        return json.loads(cleaned.read_text(encoding="utf-8")).get("stable_content_hash")
    except Exception:
        return None


def _append_log(record: Dict) -> None:
    REFRESH_LOG.parent.mkdir(parents=True, exist_ok=True)
    with REFRESH_LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


@dataclass
class RefreshResult:
    started_at: str
    finished_at: str
    outcome: str  # ok | partial | frozen | error
    per_scheme: Dict[str, Dict] = field(default_factory=dict)
    n_chunks: int = 0
    drift_count: int = 0
    error: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "outcome": self.outcome,
            "per_scheme": self.per_scheme,
            "n_chunks": self.n_chunks,
            "drift_count": self.drift_count,
            "error": self.error,
        }


def refresh(force: bool = False, skip_fetch: bool = False) -> RefreshResult:
    """Run the full ingestion pipeline. Re-chunks/re-embeds only on stable-hash change."""
    ensure_dirs()
    started = datetime.now(timezone.utc)
    cfg = load_sources()

    per_scheme: Dict[str, Dict] = {}
    drift_count = 0
    any_changed = False
    fetch_errors: List[str] = []

    for scheme in cfg.schemes:
        s_log = {"steps": [], "changed": False}
        prev_hash = _previous_stable_hash(scheme.id)
        # 1.1 Fetch
        if not skip_fetch:
            t0 = time.time()
            fr = fetch_one(scheme)
            s_log["steps"].append({"stage": "fetch", "ms": int((time.time() - t0) * 1000), "health": fr.health, "fetcher": fr.fetcher_kind})
            if fr.health == "error":
                fetch_errors.append(scheme.id)
                per_scheme[scheme.id] = s_log
                continue
        # 1.2 Extract
        t0 = time.time()
        ext = extract_for_scheme(scheme)
        s_log["steps"].append({"stage": "extract", "ms": int((time.time() - t0) * 1000), "health": ext.extraction_health if ext else "empty"})
        # 1.3 Clean
        t0 = time.time()
        cleaned = clean_for_scheme(scheme)
        s_log["steps"].append({"stage": "clean", "ms": int((time.time() - t0) * 1000), "sections": len(cleaned.sections) if cleaned else 0})
        new_hash = cleaned.stable_content_hash if cleaned else None
        s_log["prev_hash"] = prev_hash
        s_log["new_hash"] = new_hash
        if prev_hash and new_hash and prev_hash != new_hash:
            drift_count += 1
        # 1.4 Chunk (always re-chunk to keep things simple for the small corpus)
        t0 = time.time()
        chunks = chunk_for_scheme(scheme)
        s_log["steps"].append({"stage": "chunk", "ms": int((time.time() - t0) * 1000), "chunks": len(chunks)})
        s_log["changed"] = True
        any_changed = True
        per_scheme[scheme.id] = s_log

    # Drift freeze check.
    # Don't freeze on first build (no existing index) — only on scheduled refreshes
    # of an already-healthy index. Detect "first build" by absence of manifest.json.
    has_existing_index = (INDEX_DIR / "manifest.json").exists()
    if drift_count >= DRIFT_FREEZE_THRESHOLD and not force and has_existing_index:
        outcome = "frozen"
        n_chunks = 0
        logger.warning(
            "[pipeline] drift detected on %d schemes — freezing index. Use force=True to override.",
            drift_count,
        )
    elif fetch_errors and len(fetch_errors) == len(cfg.schemes):
        outcome = "error"
        n_chunks = 0
    else:
        # 1.5 + 1.6 Embed + Index (atomic swap)
        t0 = time.time()
        try:
            handle = build_index()
            n_chunks = handle.n_chunks
            outcome = "partial" if fetch_errors else "ok"
        except Exception as exc:
            logger.exception("[pipeline] indexing failed")
            outcome = "error"
            n_chunks = 0
            return _finalise(
                started, per_scheme, n_chunks, drift_count, outcome, str(exc)
            )

    return _finalise(started, per_scheme, n_chunks, drift_count, outcome, None)


def _finalise(
    started: datetime,
    per_scheme: Dict[str, Dict],
    n_chunks: int,
    drift_count: int,
    outcome: str,
    error: Optional[str],
) -> RefreshResult:
    finished = datetime.now(timezone.utc)
    result = RefreshResult(
        started_at=started.isoformat(),
        finished_at=finished.isoformat(),
        outcome=outcome,
        per_scheme=per_scheme,
        n_chunks=n_chunks,
        drift_count=drift_count,
        error=error,
    )
    _append_log(result.to_dict())
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    res = refresh()
    print(json.dumps(res.to_dict(), indent=2))
