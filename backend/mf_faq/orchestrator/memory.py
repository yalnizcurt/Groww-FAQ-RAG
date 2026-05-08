"""Session memory — lightweight in-process conversation context per session.

Tracks:
  - last discussed scheme (so "what about exit load?" works after asking about expense ratio)
  - last discussed metric
  - last N exchanges for conversational continuity

Thread-safe via a simple dict keyed by session_id.  TTL-based eviction keeps
memory bounded for a single-worker FastAPI process.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class Exchange:
    query: str
    scheme_id: Optional[str]
    metric: Optional[str]
    intent: str
    ts: float = field(default_factory=time.time)


@dataclass
class SessionContext:
    session_id: str
    last_scheme_id: Optional[str] = None
    last_scheme_name: Optional[str] = None
    last_metric: Optional[str] = None
    exchanges: List[Exchange] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)

    MAX_EXCHANGES = 20

    def record(
        self,
        query: str,
        scheme_id: Optional[str],
        scheme_name: Optional[str],
        metric: Optional[str],
        intent: str,
    ) -> None:
        if scheme_id:
            self.last_scheme_id = scheme_id
        if scheme_name:
            self.last_scheme_name = scheme_name
        if metric:
            self.last_metric = metric
        self.exchanges.append(
            Exchange(query=query, scheme_id=scheme_id, metric=metric, intent=intent)
        )
        if len(self.exchanges) > self.MAX_EXCHANGES:
            self.exchanges = self.exchanges[-self.MAX_EXCHANGES:]
        self.last_active = time.time()

    @property
    def has_context(self) -> bool:
        return self.last_scheme_id is not None

    @property
    def turn_count(self) -> int:
        return len(self.exchanges)


# ---------------------------------------------------------------------------
# Global session store (single-process only; fine for uvicorn --workers 1).
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_sessions: Dict[str, SessionContext] = {}
_SESSION_TTL = 1800  # 30 minutes


def get_session(session_id: str) -> SessionContext:
    with _lock:
        _evict_stale()
        if session_id not in _sessions:
            _sessions[session_id] = SessionContext(session_id=session_id)
        return _sessions[session_id]


def _evict_stale() -> None:
    now = time.time()
    stale = [k for k, v in _sessions.items() if now - v.last_active > _SESSION_TTL]
    for k in stale:
        del _sessions[k]


# ---------------------------------------------------------------------------
# Query expansion — map natural language to factual field names.
# ---------------------------------------------------------------------------

_FIELD_SYNONYMS: Dict[str, str] = {
    "risk": "riskometer",
    "risk level": "riskometer",
    "risky": "riskometer",
    "riskometer": "riskometer",
    "fees": "expense ratio",
    "fee": "expense ratio",
    "charges": "expense ratio",
    "expense": "expense ratio",
    "expense ratio": "expense ratio",
    "ter": "expense ratio",
    "exit load": "exit load",
    "exit charge": "exit load",
    "withdrawal charge": "exit load",
    "withdrawal fee": "exit load",
    "redemption charge": "exit load",
    "lock-in": "lock-in period",
    "lockin": "lock-in period",
    "lock in": "lock-in period",
    "lock in period": "lock-in period",
    "minimum sip": "minimum SIP",
    "min sip": "minimum SIP",
    "sip amount": "minimum SIP",
    "sip minimum": "minimum SIP",
    "minimum investment": "minimum SIP",
    "minimum amount": "minimum SIP",
    "min investment": "minimum SIP",
    "how much to invest": "minimum SIP",
    "how much do i need": "minimum SIP",
    "nav": "NAV",
    "aum": "AUM",
    "fund size": "AUM",
    "size": "AUM",
    "benchmark": "benchmark",
    "index": "benchmark",
    "category": "fund category",
    "fund category": "fund category",
    "type": "fund category",
    "fund manager": "fund manager",
    "manager": "fund manager",
    "who manages": "fund manager",
    "who is managing": "fund manager",
    "managing": "fund manager",
    "managed by": "fund manager",
    "who runs": "fund manager",
}


def detect_metric(query: str) -> Optional[str]:
    """Extract the factual field the user is asking about."""
    q = query.lower().strip()
    best: Optional[Tuple[str, str]] = None
    for synonym, canonical in _FIELD_SYNONYMS.items():
        if synonym in q:
            if best is None or len(synonym) > len(best[0]):
                best = (synonym, canonical)
    return best[1] if best else None
