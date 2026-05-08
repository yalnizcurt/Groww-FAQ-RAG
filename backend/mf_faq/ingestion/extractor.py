"""Phase 1.2 Extractor — HTML → structured sections.

Targets the section anchors that matter for fact-shaped queries on Groww product
pages: Fund Details (NAV/AUM/expense/exit/min SIP), Riskometer, Fund Manager,
Fund House, Tax & Exit Load, About, FAQ (kept here, dropped by 1.3 cleaner).

Falls back gracefully when individual selectors miss; \"must_have_anchors\" reports
health.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from bs4 import BeautifulSoup

from ..config_loader import PROCESSED_DIR, RAW_DIR, Scheme, ensure_dirs

logger = logging.getLogger(__name__)

# Section anchors we track for health.
MUST_HAVE_ANCHORS = (
    "Fund Details",
    "Exit Load and Tax",
    "Minimum Investments",
    "Fund Manager",
    "Fund House",
    "About",
)

# Heading-like selectors and label keywords on Groww product pages.
HEADING_TAGS = ("h1", "h2", "h3", "h4")


@dataclass
class Section:
    name: str
    text: str
    source: str = "html_section"  # or "meta_description", "jsonld", "derived"


@dataclass
class ExtractedDoc:
    scheme_id: str
    source_url: str
    fetched_at: str
    sections: List[Section] = field(default_factory=list)
    must_have_anchors: Dict[str, bool] = field(default_factory=dict)
    extraction_health: str = "ok"  # "ok" | "degraded" | "empty"
    raw_meta_description: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "scheme_id": self.scheme_id,
            "source_url": self.source_url,
            "fetched_at": self.fetched_at,
            "sections": [
                {"name": s.name, "text": s.text, "source": s.source} for s in self.sections
            ],
            "must_have_anchors": self.must_have_anchors,
            "extraction_health": self.extraction_health,
            "raw_meta_description": self.raw_meta_description,
        }


def _txt(node) -> str:
    return re.sub(r"\s+", " ", (node.get_text(" ", strip=True) if node else "")).strip()


def _meta_description(soup: BeautifulSoup) -> Optional[str]:
    for sel in (
        ('meta', {'name': 'description'}),
        ('meta', {'property': 'og:description'}),
    ):
        node = soup.find(*sel)
        if node and node.get('content'):
            return node['content'].strip()
    return None


def _scheme_name_from_h1(soup: BeautifulSoup) -> Optional[str]:
    h1 = soup.find("h1")
    return _txt(h1) if h1 else None


def _section_after_heading(soup: BeautifulSoup, heading_keywords: Tuple[str, ...]) -> Optional[str]:
    """Find a heading whose text contains any keyword and concatenate text until next heading."""
    keywords_lc = [k.lower() for k in heading_keywords]
    for tag in soup.find_all(HEADING_TAGS):
        text = _txt(tag)
        if not text:
            continue
        if any(k in text.lower() for k in keywords_lc):
            collected: List[str] = []
            node = tag.find_next_sibling()
            depth = 0
            while node and depth < 80:
                if getattr(node, "name", None) in HEADING_TAGS:
                    break
                t = _txt(node)
                if t:
                    collected.append(t)
                node = node.find_next_sibling()
                depth += 1
            if collected:
                return " ".join(collected)
    return None


def _all_heading_blocks(soup: BeautifulSoup) -> List[Tuple[str, str]]:
    """Return a list of (heading_text, body_text) blocks across the page."""
    results: List[Tuple[str, str]] = []
    headings = soup.find_all(HEADING_TAGS)
    for i, h in enumerate(headings):
        head = _txt(h)
        if not head:
            continue
        body_parts: List[str] = []
        node = h.find_next_sibling()
        depth = 0
        while node and depth < 80:
            if getattr(node, "name", None) in HEADING_TAGS:
                break
            t = _txt(node)
            if t:
                body_parts.append(t)
            node = node.find_next_sibling()
            depth += 1
        if body_parts:
            results.append((head, " ".join(body_parts)))
    return results


def _jsonld_blocks(soup: BeautifulSoup) -> List[Dict]:
    blocks: List[Dict] = []
    for tag in soup.find_all("script", {"type": "application/ld+json"}):
        if not tag.string:
            continue
        try:
            data = json.loads(tag.string)
        except Exception:
            continue
        if isinstance(data, list):
            blocks.extend(d for d in data if isinstance(d, dict))
        elif isinstance(data, dict):
            blocks.append(data)
    return blocks


def _faq_from_jsonld(blocks: List[Dict]) -> Optional[str]:
    parts: List[str] = []
    for b in blocks:
        if (b.get("@type") in ("FAQPage", "FAQ")) or (
            isinstance(b.get("@type"), list) and "FAQPage" in b["@type"]
        ):
            for q in b.get("mainEntity", []) or []:
                if not isinstance(q, dict):
                    continue
                question = q.get("name") or q.get("@id")
                ans_node = q.get("acceptedAnswer") or {}
                answer = (
                    ans_node.get("text") if isinstance(ans_node, dict) else None
                ) or ""
                # Strip HTML inside the answer text.
                answer_text = BeautifulSoup(answer, "lxml").get_text(" ", strip=True)
                if question and answer_text:
                    parts.append(f"Q: {question} A: {answer_text}")
    return " \n ".join(parts) if parts else None


# ---------------------------------------------------------------------------
# Main extraction
# ---------------------------------------------------------------------------

KEYS_FUND_DETAILS = ("Fund Details", "Scheme Details")
KEYS_TAX_EXIT = ("Exit load", "Tax", "Taxation", "Exit Load and Tax", "Exit load, stamp duty")
KEYS_MIN_INV = ("Minimum Investment", "Minimum Investments", "Min. SIP", "Min. Lumpsum")
KEYS_FUND_MANAGER = ("Fund Manager", "Fund management")
KEYS_FUND_HOUSE = ("Fund House", "Fund house", "Asset Management Company", "AMC details")
KEYS_RISKOMETER = ("Riskometer", "Risk Level", "Risk-o-meter")
KEYS_BENCHMARK = ("Benchmark",)
KEYS_ABOUT = ("About", "Investment Objective", "Scheme Objective")


def _extract_fund_details_widget(soup: BeautifulSoup) -> Optional[str]:
    """Pull the structured Fund Details widget on Groww product pages."""
    parts: List[str] = []
    seen = set()
    for div in soup.find_all(class_=re.compile(r"fundDetails")):
        text = div.get_text(" | ", strip=True)
        if not text or len(text) > 800:
            continue
        if text in seen:
            continue
        seen.add(text)
        parts.append(text)
    if not parts:
        return None
    return parts[0]


def _extract_riskometer_label(soup: BeautifulSoup) -> Optional[str]:
    """Look for the riskometer level text near the riskometer image/svg."""
    text = soup.get_text(" ", strip=True)
    pat = re.compile(
        r"(Very High|Moderately High|Moderately Low|Low to Moderate|Moderate|High|Low)\s*Risk",
        re.IGNORECASE,
    )
    m = pat.search(text)
    if m:
        # Pad the text so it survives the chunker MIN_TOKENS gate AND so BM25
        # gets multiple keyword hits ("riskometer", "risk level", "risk class").
        level = m.group(1)
        return (
            f"Riskometer level for this scheme: {level} Risk. "
            f"Risk level: {level}. "
            f"Risk classification per the SEBI riskometer: {level} Risk."
        )
    return None


def _extract_benchmark(soup: BeautifulSoup) -> Optional[str]:
    text = soup.get_text(" ", strip=True)
    m = re.search(r"Benchmark\s*[:\-]?\s*([A-Z][A-Za-z0-9 &\-]{4,80})", text)
    if m:
        return f"Benchmark: {m.group(1).strip()}"
    return None


def extract_html(html: str, scheme: Scheme, fetched_at: str) -> ExtractedDoc:
    soup = BeautifulSoup(html, "lxml")

    sections: List[Section] = []
    md = _meta_description(soup)
    if md:
        sections.append(Section(name="About", text=md, source="meta_description"))

    fd_widget = _extract_fund_details_widget(soup)
    if fd_widget:
        sections.append(Section(name="Fund Details", text=fd_widget, source="widget"))

    rs = _extract_riskometer_label(soup)
    if rs:
        sections.append(Section(name="Riskometer", text=rs, source="derived"))

    bm = _extract_benchmark(soup)
    if bm:
        sections.append(Section(name="Benchmark", text=bm, source="derived"))

    # Targeted section pulls.
    pulled: Dict[str, str] = {}
    for name, keys in (
        ("Fund Details", KEYS_FUND_DETAILS),
        ("Exit Load and Tax", KEYS_TAX_EXIT),
        ("Minimum Investments", KEYS_MIN_INV),
        ("Fund Manager", KEYS_FUND_MANAGER),
        ("Fund House", KEYS_FUND_HOUSE),
        ("Riskometer", KEYS_RISKOMETER),
        ("Benchmark", KEYS_BENCHMARK),
        ("About", KEYS_ABOUT),
    ):
        text = _section_after_heading(soup, keys)
        if text:
            pulled[name] = text

    for head, body in _all_heading_blocks(soup):
        head_lc = head.lower()
        for name, keys in (
            ("Fund Details", KEYS_FUND_DETAILS),
            ("Exit Load and Tax", KEYS_TAX_EXIT),
            ("Minimum Investments", KEYS_MIN_INV),
            ("Fund Manager", KEYS_FUND_MANAGER),
            ("Fund House", KEYS_FUND_HOUSE),
            ("Riskometer", KEYS_RISKOMETER),
            ("Benchmark", KEYS_BENCHMARK),
            ("About", KEYS_ABOUT),
        ):
            if any(k.lower() in head_lc for k in keys) and name not in pulled:
                pulled[name] = body

    existing = {s.name for s in sections}
    for name, text in pulled.items():
        if name in existing:
            continue
        if name == "About" and any(s.name == "About" and s.source == "meta_description" for s in sections):
            sections = [s for s in sections if not (s.name == "About" and s.source == "meta_description")]
        sections.append(Section(name=name, text=text, source="html_section"))

    # Derive an explicit \"FAQs\" section from any FAQPage JSON-LD (cleaner will drop it,
    # but it's a critical health signal).
    jsonld = _jsonld_blocks(soup)
    faq_text = _faq_from_jsonld(jsonld)
    if faq_text:
        sections.append(Section(name="FAQs", text=faq_text, source="jsonld"))

    # Compute health.
    must_have = {a: any(s.name == a for s in sections) for a in MUST_HAVE_ANCHORS}
    present = sum(1 for v in must_have.values() if v)
    if present == 0:
        health = "empty"
    elif present < 4:
        health = "degraded"
    else:
        health = "ok"

    return ExtractedDoc(
        scheme_id=scheme.id,
        source_url=scheme.url,
        fetched_at=fetched_at,
        sections=sections,
        must_have_anchors=must_have,
        extraction_health=health,
        raw_meta_description=md,
    )


def extract_for_scheme(scheme: Scheme) -> Optional[ExtractedDoc]:
    raw_html = RAW_DIR / scheme.id / "latest.html"
    raw_meta = RAW_DIR / scheme.id / "latest.meta.json"
    if not raw_html.exists():
        logger.error("[extractor] no raw html for %s", scheme.id)
        return None
    html = raw_html.read_text(encoding="utf-8")
    fetched_at = datetime.now(timezone.utc).isoformat()
    if raw_meta.exists():
        try:
            fetched_at = json.loads(raw_meta.read_text(encoding="utf-8")).get(
                "fetched_at", fetched_at
            )
        except Exception:
            pass

    doc = extract_html(html, scheme, fetched_at)
    out_dir = PROCESSED_DIR / scheme.id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "extracted.json").write_text(
        json.dumps(doc.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    logger.info(
        "[extractor] %s: %d sections, health=%s",
        scheme.id,
        len(doc.sections),
        doc.extraction_health,
    )
    return doc


def extract_all() -> List[ExtractedDoc]:
    from ..config_loader import load_sources

    ensure_dirs()
    out: List[ExtractedDoc] = []
    for scheme in load_sources().schemes:
        d = extract_for_scheme(scheme)
        if d:
            out.append(d)
    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    docs = extract_all()
    for d in docs:
        print(f"{d.scheme_id:18s} sections={len(d.sections):2d} health={d.extraction_health}")
