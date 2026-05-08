"""Post-processor — enforce URL policy, sentence cap, banned tokens, suggestions.

URL policy:
  - PII detected            → 0 URLs
  - low confidence / no hit → 0 URLs
  - refusal (advice/etc.)   → exactly 1 whitelisted URL
  - successful factual      → exactly 1 whitelisted URL
  - greeting / conversational→ 0 URLs
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from typing import List, Optional

from ..config_loader import (
    extract_urls,
    is_whitelisted_url,
    load_refusals,
    load_sources,
    whitelisted_urls,
)

MAX_SENTENCES = 3

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\u20b9\d])")


def sentence_count(text: str) -> int:
    parts = [p for p in _SENT_SPLIT.split(text or "") if p.strip()]
    return len(parts)


def trim_sentences(text: str, max_n: int = MAX_SENTENCES) -> str:
    parts = [p for p in _SENT_SPLIT.split(text or "") if p.strip()]
    if len(parts) <= max_n:
        return " ".join(parts).strip()
    return " ".join(parts[:max_n]).strip()


def strip_urls(text: str) -> str:
    return re.sub(r"https?://\S+", "", text or "").strip()


def has_banned_tokens(text: str) -> List[str]:
    cfg = load_refusals()
    lc = (text or "").lower()
    found: List[str] = []
    for tok in cfg.banned_tokens:
        t = tok.lower()
        if t and t in lc:
            found.append(tok)
    return found


# ---------------------------------------------------------------------------
# Suggestion chips — context-aware follow-ups.
# ---------------------------------------------------------------------------

_FACTUAL_FIELDS = [
    "expense ratio",
    "exit load",
    "riskometer",
    "benchmark",
    "lock-in period",
    "minimum SIP",
    "fund manager",
    "AUM",
    "NAV",
    "fund category",
]


def generate_suggestions(
    scheme_id: Optional[str],
    scheme_name: Optional[str],
    last_metric: Optional[str],
    intent: str,
) -> List[str]:
    """Generate 2-4 context-aware follow-up suggestion chips."""
    if not scheme_id or not scheme_name:
        # No scheme context — suggest scheme-level exploration.
        cfg = load_sources()
        names = [s.name.replace(" - Direct Growth", "").replace(" - Direct Plan Growth", "")
                 for s in cfg.schemes[:3]]
        return [f"Expense ratio of {n}" for n in names[:2]] + ["What schemes do you cover?"]

    short_name = scheme_name.replace(" - Direct Growth", "").replace(" - Direct Plan Growth", "")

    # Pick fields the user hasn't just asked about.
    available = [f for f in _FACTUAL_FIELDS if f != last_metric]
    random.shuffle(available)
    picks = available[:3]

    suggestions = []
    for p in picks:
        suggestions.append(f"{p.capitalize()} of {short_name}")

    return suggestions[:3]


# ---------------------------------------------------------------------------
# FinalAnswer dataclass
# ---------------------------------------------------------------------------


@dataclass
class FinalAnswer:
    body: str
    citation_url: Optional[str]
    last_updated: Optional[str]
    intent: str
    scheme_id: Optional[str] = None
    chunk_ids: List[str] = field(default_factory=list)
    confidence: float = 0.0
    full_text: str = ""
    post_check_passed: bool = True
    notes: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)

    def render(self) -> str:
        out = self.body.strip()
        if self.citation_url:
            out += f"\n\nSource: {self.citation_url}"
        if self.last_updated:
            out += f"\nLast updated from sources: {self.last_updated}"
        return out.strip()


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def build_factual(
    body: str,
    citation_url: str,
    last_updated: Optional[str],
    chunk_ids: List[str],
    confidence: float,
    scheme_id: Optional[str],
    scheme_name: Optional[str] = None,
    last_metric: Optional[str] = None,
) -> FinalAnswer:
    notes: List[str] = []
    body = strip_urls(body)
    body = trim_sentences(body, MAX_SENTENCES)
    extra_urls = extract_urls(body)
    for u in extra_urls:
        body = body.replace(u, "").strip()
    banned = has_banned_tokens(body)
    if banned:
        notes.append(f"banned_tokens:{','.join(banned)}")
        body = load_refusals().dont_know_without_link
        return FinalAnswer(
            body=body,
            citation_url=None,
            last_updated=None,
            intent="dont_know",
            chunk_ids=chunk_ids,
            confidence=confidence,
            scheme_id=scheme_id,
            full_text=body,
            post_check_passed=False,
            notes=notes,
            suggestions=generate_suggestions(scheme_id, scheme_name, last_metric, "dont_know"),
        )
    if not is_whitelisted_url(citation_url):
        notes.append("non_whitelisted_url")
        body = load_refusals().dont_know_without_link
        return FinalAnswer(
            body=body,
            citation_url=None,
            last_updated=None,
            intent="dont_know",
            chunk_ids=chunk_ids,
            confidence=confidence,
            scheme_id=scheme_id,
            full_text=body,
            post_check_passed=False,
            notes=notes,
        )
    final = FinalAnswer(
        body=body,
        citation_url=citation_url,
        last_updated=last_updated,
        intent="factual",
        chunk_ids=chunk_ids,
        confidence=confidence,
        scheme_id=scheme_id,
        notes=notes,
        suggestions=generate_suggestions(scheme_id, scheme_name, last_metric, "factual"),
    )
    final.full_text = final.render()
    return final


def build_refusal(
    body: str,
    citation_url: str,
    intent_id: str,
    scheme_id: Optional[str],
    scheme_name: Optional[str] = None,
) -> FinalAnswer:
    notes: List[str] = []
    body = strip_urls(body)
    body = trim_sentences(body, MAX_SENTENCES)
    if not is_whitelisted_url(citation_url):
        notes.append("refusal_url_not_whitelisted")
        wl = whitelisted_urls()
        if wl:
            citation_url = wl[0]
    final = FinalAnswer(
        body=body,
        citation_url=citation_url,
        last_updated=None,
        intent=intent_id,
        chunk_ids=[],
        confidence=0.0,
        scheme_id=scheme_id,
        notes=notes,
        suggestions=generate_suggestions(scheme_id, scheme_name, None, intent_id),
    )
    final.full_text = final.render()
    return final


def build_dont_know(
    scheme_id: Optional[str] = None,
    scheme_name: Optional[str] = None,
) -> FinalAnswer:
    cfg = load_refusals()
    body = cfg.dont_know_without_link
    final = FinalAnswer(
        body=body,
        citation_url=None,
        last_updated=None,
        intent="dont_know",
        chunk_ids=[],
        confidence=0.0,
        scheme_id=scheme_id,
        suggestions=generate_suggestions(scheme_id, scheme_name, None, "dont_know"),
    )
    final.full_text = final.render()
    return final


def build_pii_block() -> FinalAnswer:
    cfg = load_refusals()
    body = cfg.pii_block
    final = FinalAnswer(
        body=body,
        citation_url=None,
        last_updated=None,
        intent="pii",
        chunk_ids=[],
        confidence=0.0,
        scheme_id=None,
    )
    final.full_text = final.render()
    return final


def build_greeting() -> FinalAnswer:
    cfg = load_refusals()
    body = getattr(cfg, "greeting", None) or (
        "Hey! I'm the Groww Mutual Fund Facts Assistant. I can look up "
        "expense ratio, exit load, risk level, lock-in, benchmark, or SIP "
        "minimum for HDFC mutual fund schemes. What would you like to know?"
    )
    return FinalAnswer(
        body=body,
        citation_url=None,
        last_updated=None,
        intent="greeting",
        suggestions=generate_suggestions(None, None, None, "greeting"),
    )


def build_conversational_ack(
    scheme_id: Optional[str] = None,
    scheme_name: Optional[str] = None,
    last_metric: Optional[str] = None,
) -> FinalAnswer:
    cfg = load_refusals()

    # Contextual ack if we know what they were discussing.
    if scheme_name:
        short = scheme_name.replace(" - Direct Growth", "").replace(" - Direct Plan Growth", "")
        body = (
            f"Sure thing! Let me know if you'd like to check anything else "
            f"about {short} — I can look up expense ratio, exit load, risk level, "
            f"lock-in, benchmark, or SIP minimum."
        )
    else:
        body = getattr(cfg, "conversational_ack", None) or (
            "Got it! Let me know if you'd like to check anything else — I can "
            "look up expense ratio, exit load, risk level, lock-in, benchmark, "
            "or SIP minimum."
        )

    return FinalAnswer(
        body=body,
        citation_url=None,
        last_updated=None,
        intent="conversational",
        scheme_id=scheme_id,
        suggestions=generate_suggestions(scheme_id, scheme_name, last_metric, "conversational"),
    )
