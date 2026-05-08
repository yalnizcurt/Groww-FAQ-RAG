"""Scheme resolver — longest substring match against scheme name + aliases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from ..config_loader import Scheme, load_sources


@dataclass(frozen=True)
class SchemeMatch:
    scheme: Scheme
    matched_term: str
    confidence: float  # 0..1


def resolve(query: str) -> Optional[SchemeMatch]:
    if not query:
        return None
    q = query.lower()
    best: Optional[Tuple[Scheme, str, float]] = None
    for s in load_sources().schemes:
        candidates: List[str] = [s.name, *list(s.aliases), s.id.replace("_", " ")]
        for term in candidates:
            t = term.lower().strip()
            if not t:
                continue
            if t in q:
                # Longer matches are more specific.
                conf = min(1.0, max(0.5, len(t) / max(8, len(s.name))))
                if best is None or len(t) > len(best[1]):
                    best = (s, t, conf)
    if best is None:
        return None
    return SchemeMatch(scheme=best[0], matched_term=best[1], confidence=best[2])
