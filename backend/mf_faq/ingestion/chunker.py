"""Phase 1.4 Chunker — section-aware splitting with full provenance metadata.

On the small Groww corpus (5 schemes × ~7 sections), most sections are < 250
tokens, so the default emission is one chunk per section. Long sections (e.g.
About) are split on sentence boundaries with a soft cap of 250 tokens.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional

from ..config_loader import PROCESSED_DIR, Scheme, ensure_dirs, load_sources
from .cleaner import CleanedDoc
from .extractor import Section

logger = logging.getLogger(__name__)

SOFT_TOKEN_CAP = 250
HARD_TOKEN_CAP = 400
OVERLAP_TOKENS = 30
MIN_TOKENS_FOR_CHUNK = 5


@dataclass
class Chunk:
    chunk_id: str
    scheme_id: str
    scheme_name: str
    doc_type: str
    source_url: str
    section: str
    section_source: str
    last_updated: str
    content_hash: str
    stable_content_hash: str
    text: str

    def to_dict(self) -> dict:
        return self.__dict__.copy()


# Cheap word-based token counting; we only need rough buckets here.
_WORD_RE = re.compile(r"\S+")


def _token_count(text: str) -> int:
    return len(_WORD_RE.findall(text))


_SENT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\u20b9\d])")


def _split_sentences(text: str) -> List[str]:
    sents = _SENT_RE.split(text)
    return [s.strip() for s in sents if s.strip()]


def _split_long(text: str) -> List[str]:
    """Split a long section into chunks not exceeding SOFT_TOKEN_CAP, with overlap."""
    sents = _split_sentences(text)
    if not sents:
        return [text]
    chunks: List[str] = []
    buf: List[str] = []
    buf_tokens = 0
    for s in sents:
        s_tokens = _token_count(s)
        if buf_tokens + s_tokens > SOFT_TOKEN_CAP and buf:
            chunks.append(" ".join(buf))
            # carry over the last few words for overlap.
            if OVERLAP_TOKENS > 0 and chunks[-1]:
                tail = chunks[-1].split()[-OVERLAP_TOKENS:]
                buf = [" ".join(tail)]
                buf_tokens = len(tail)
            else:
                buf = []
                buf_tokens = 0
        buf.append(s)
        buf_tokens += s_tokens
        if buf_tokens >= HARD_TOKEN_CAP:
            chunks.append(" ".join(buf))
            buf = []
            buf_tokens = 0
    if buf:
        chunks.append(" ".join(buf))
    return chunks


def chunk_doc(doc: CleanedDoc, scheme: Scheme) -> Iterable[Chunk]:
    for s in doc.sections:
        text = s.text.strip()
        if not text or _token_count(text) < MIN_TOKENS_FOR_CHUNK:
            continue
        # If short enough, emit one chunk per section.
        pieces = [text] if _token_count(text) <= SOFT_TOKEN_CAP else _split_long(text)
        for piece in pieces:
            piece_clean = piece.strip()
            if not piece_clean or _token_count(piece_clean) < MIN_TOKENS_FOR_CHUNK:
                continue
            chash = (
                "sha256:"
                + hashlib.sha256(
                    f"{doc.scheme_id}::{s.name}::{piece_clean}".encode("utf-8")
                ).hexdigest()
            )
            yield Chunk(
                chunk_id=str(uuid.uuid4()),
                scheme_id=doc.scheme_id,
                scheme_name=scheme.name,
                doc_type=scheme.doc_type,
                source_url=doc.source_url,
                section=s.name,
                section_source=s.source,
                last_updated=doc.last_updated,
                content_hash=chash,
                stable_content_hash=doc.stable_content_hash,
                text=piece_clean,
            )


def chunk_for_scheme(scheme: Scheme) -> List[Chunk]:
    cleaned_path = PROCESSED_DIR / scheme.id / "cleaned.json"
    if not cleaned_path.exists():
        logger.error("[chunker] missing cleaned.json for %s", scheme.id)
        return []
    raw = json.loads(cleaned_path.read_text(encoding="utf-8"))
    doc = CleanedDoc(
        scheme_id=raw["scheme_id"],
        source_url=raw["source_url"],
        fetched_at=raw["fetched_at"],
        cleaned_at=raw["cleaned_at"],
        sections=[
            Section(name=s["name"], text=s["text"], source=s.get("source", "html_section"))
            for s in raw["sections"]
        ],
        last_updated=raw.get("last_updated", ""),
        content_hash=raw.get("content_hash", ""),
        stable_content_hash=raw.get("stable_content_hash", ""),
    )
    chunks = list(chunk_doc(doc, scheme))
    out_path = PROCESSED_DIR / scheme.id / "chunks.jsonl"
    with out_path.open("w", encoding="utf-8") as fh:
        for ch in chunks:
            fh.write(json.dumps(ch.to_dict(), ensure_ascii=False) + "\n")
    logger.info("[chunker] %s: %d chunks", scheme.id, len(chunks))
    return chunks


def chunk_all() -> List[Chunk]:
    ensure_dirs()
    all_chunks: List[Chunk] = []
    for scheme in load_sources().schemes:
        all_chunks.extend(chunk_for_scheme(scheme))
    return all_chunks


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    out = chunk_all()
    print(f"total chunks: {len(out)}")
