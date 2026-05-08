"""Phase 1.3 Cleaner & Normalizer.

Drops boilerplate, normalises Unicode + currency, removes the FAQ section, and
trims Fund Manager bios + Fund House contact lines per architecture.md (1.3).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..config_loader import PROCESSED_DIR, Scheme, ensure_dirs, load_sources
from .extractor import ExtractedDoc, Section

logger = logging.getLogger(__name__)

# Boilerplate snippets (case-insensitive substring match).
BOILERPLATE_SUBSTRINGS = (
    "mutual fund investments are subject to market risks",
    "please read all scheme related documents",
    "you may also like",
    "download the groww app",
    "explore funds by",
    "share with friends",
    "copy link",
    "copyright",
    "all rights reserved",
    "sebi disclaimer",
    "investments in mutual funds are",
    "start investing now",
)

# Volatile fields stripped before computing the stable hash.
VOLATILE_PATTERNS = (
    re.compile(r"NAV\s*[:\-]?\s*\u20b9?\s*[0-9.,]+", re.IGNORECASE),
    re.compile(r"as on [0-9A-Za-z, ]+", re.IGNORECASE),
    re.compile(r"updated on [0-9A-Za-z, ]+", re.IGNORECASE),
    re.compile(r"\b(today|yesterday)\b", re.IGNORECASE),
)

# Patterns we strip from Fund Manager (keep just name + tenure).
MANAGER_BIO_PATTERNS = (
    re.compile(r"Education[:\-]?[\s\S]+?(?=Experience|Other Funds|$)", re.IGNORECASE),
    re.compile(r"Experience[:\-]?[\s\S]+?(?=Other Funds|Education|$)", re.IGNORECASE),
)

# Patterns we strip from Fund House (keep AMC info; drop contacts).
FUND_HOUSE_CONTACT_PATTERNS = (
    re.compile(r"Address[:\-]?\s+[^.]*\.", re.IGNORECASE),
    re.compile(r"Phone[:\-]?\s+[+0-9\-() ]+", re.IGNORECASE),
    re.compile(r"Email[:\-]?\s+\S+@\S+\.[a-z]{2,}", re.IGNORECASE),
    re.compile(
        r"(Website|Web)[:\-]?\s+https?://\S+", re.IGNORECASE
    ),
)


@dataclass
class CleanedDoc:
    scheme_id: str
    source_url: str
    fetched_at: str
    cleaned_at: str
    sections: List[Section] = field(default_factory=list)
    last_updated: str = ""
    content_hash: str = ""
    stable_content_hash: str = ""

    def to_dict(self) -> Dict:
        return {
            "scheme_id": self.scheme_id,
            "source_url": self.source_url,
            "fetched_at": self.fetched_at,
            "cleaned_at": self.cleaned_at,
            "last_updated": self.last_updated,
            "content_hash": self.content_hash,
            "stable_content_hash": self.stable_content_hash,
            "sections": [
                {"name": s.name, "text": s.text, "source": s.source} for s in self.sections
            ],
        }


def _nfkc(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "")


def _normalise_currency(text: str) -> str:
    # Rs. 500 / Rs 500 / INR 500 → \u20b9 500
    text = re.sub(r"\bRs\.?\s*", "\u20b9", text)
    text = re.sub(r"\bINR\s*", "\u20b9", text)
    # Collapse multiple spaces around \u20b9.
    text = re.sub(r"\u20b9\s+", "\u20b9", text)
    return text


def _strip_smart_quotes(text: str) -> str:
    return (
        text.replace("\u2018", "'")
        .replace("\u2019", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u2013", "-")
        .replace("\u2014", "-")
    )


def _drop_boilerplate(text: str) -> str:
    if not text:
        return text
    out = text
    lower = out.lower()
    for snip in BOILERPLATE_SUBSTRINGS:
        idx = lower.find(snip)
        while idx != -1:
            # Drop from idx until end of sentence.
            end = out.find(".", idx)
            if end == -1:
                end = len(out)
            else:
                end += 1
            out = (out[:idx] + out[end:]).strip()
            lower = out.lower()
            idx = lower.find(snip)
    return out


def _strip_volatile(text: str) -> str:
    out = text or ""
    for pat in VOLATILE_PATTERNS:
        out = pat.sub("", out)
    return re.sub(r"\s{2,}", " ", out).strip()


def _trim_manager(text: str) -> str:
    out = text or ""
    for pat in MANAGER_BIO_PATTERNS:
        out = pat.sub(" ", out)
    return re.sub(r"\s{2,}", " ", out).strip()


def _trim_fund_house(text: str) -> str:
    out = text or ""
    for pat in FUND_HOUSE_CONTACT_PATTERNS:
        out = pat.sub(" ", out)
    return re.sub(r"\s{2,}", " ", out).strip()


def _clean_text(text: str) -> str:
    text = _nfkc(text)
    text = _strip_smart_quotes(text)
    text = _normalise_currency(text)
    text = _drop_boilerplate(text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    return text


def clean_doc(doc: ExtractedDoc) -> CleanedDoc:
    cleaned_sections: List[Section] = []
    for s in doc.sections:
        if s.name == "FAQs":  # drop entirely per spec
            continue
        # Drop About sections that are just the marketing meta-description.
        # These contain phrases like "Get latest NAV ... Invest with Groww" and
        # are pure marketing copy, not factual content. We keep heading-derived
        # About sections (which contain the Investment Objective).
        if s.name == "About" and s.source == "meta_description":
            continue
        text = _clean_text(s.text)
        if s.name == "Fund Manager":
            text = _trim_manager(text)
        elif s.name == "Fund House":
            text = _trim_fund_house(text)
        if not text or len(text) < 5:
            continue
        cleaned_sections.append(Section(name=s.name, text=text, source=s.source))

    # Compute hashes.
    full_blob = "\n".join(f"{s.name}::{s.text}" for s in cleaned_sections)
    content_hash = "sha256:" + hashlib.sha256(full_blob.encode("utf-8")).hexdigest()
    stable_blob = "\n".join(
        f"{s.name}::{_strip_volatile(s.text)}" for s in cleaned_sections
    )
    stable_hash = "sha256:" + hashlib.sha256(stable_blob.encode("utf-8")).hexdigest()

    last_updated = (doc.fetched_at or "")[:10] if doc.fetched_at else ""

    return CleanedDoc(
        scheme_id=doc.scheme_id,
        source_url=doc.source_url,
        fetched_at=doc.fetched_at,
        cleaned_at=datetime.now(timezone.utc).isoformat(),
        sections=cleaned_sections,
        last_updated=last_updated,
        content_hash=content_hash,
        stable_content_hash=stable_hash,
    )


def clean_for_scheme(scheme: Scheme) -> Optional[CleanedDoc]:
    extracted_path = PROCESSED_DIR / scheme.id / "extracted.json"
    if not extracted_path.exists():
        logger.error("[cleaner] missing extracted.json for %s", scheme.id)
        return None
    raw = json.loads(extracted_path.read_text(encoding="utf-8"))
    doc = ExtractedDoc(
        scheme_id=raw["scheme_id"],
        source_url=raw["source_url"],
        fetched_at=raw["fetched_at"],
        sections=[
            Section(name=s["name"], text=s["text"], source=s.get("source", "html_section"))
            for s in raw["sections"]
        ],
        must_have_anchors=raw.get("must_have_anchors", {}),
        extraction_health=raw.get("extraction_health", "ok"),
    )
    cleaned = clean_doc(doc)
    out = PROCESSED_DIR / scheme.id / "cleaned.json"
    out.write_text(
        json.dumps(cleaned.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info(
        "[cleaner] %s: %d sections after cleaning", scheme.id, len(cleaned.sections)
    )
    return cleaned


def clean_all() -> List[CleanedDoc]:
    ensure_dirs()
    out: List[CleanedDoc] = []
    for scheme in load_sources().schemes:
        c = clean_for_scheme(scheme)
        if c:
            out.append(c)
    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    cleaned_docs = clean_all()
    for c in cleaned_docs:
        print(f"{c.scheme_id:18s} sections={len(c.sections):2d} stable_hash={c.stable_content_hash[:14]}")
