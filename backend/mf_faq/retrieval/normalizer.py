"""Query normalisation — NFKC, lowercase, MF token expansion."""

from __future__ import annotations

import re
import unicodedata
from typing import Dict

# Common MF acronyms we expand for retrieval.
ACRONYMS: Dict[str, str] = {
    "sip": "sip systematic investment plan",
    "swp": "swp systematic withdrawal plan",
    "stp": "stp systematic transfer plan",
    "nav": "nav net asset value",
    "aum": "aum assets under management",
    "elss": "elss equity linked savings scheme",
    "kim": "kim key information memorandum",
    "sid": "sid scheme information document",
    "sebi": "sebi securities and exchange board of india",
    "amfi": "amfi association of mutual funds in india",
    "er": "er expense ratio",
}


def normalize(query: str) -> str:
    if not query:
        return ""
    q = unicodedata.normalize("NFKC", query)
    q = q.replace("\u20b9", " rs ")
    q = q.lower()
    q = re.sub(r"[^a-z0-9%.\-\s]", " ", q)
    q = re.sub(r"\s{2,}", " ", q).strip()
    # expand common MF tokens.
    parts = q.split()
    expanded = []
    for p in parts:
        if p in ACRONYMS:
            expanded.append(ACRONYMS[p])
        else:
            expanded.append(p)
    return " ".join(expanded).strip()
