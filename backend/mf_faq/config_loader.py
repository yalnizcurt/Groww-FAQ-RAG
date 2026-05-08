"""Phase 0 — Foundation & Governance: load + validate sources.yaml and refusal_intents.yaml.

The loader enforces the closed-corpus contract from architecture.md: exactly the 5
Groww URLs are allowed, and any code path that needs to *cite* a URL must validate
against :func:`is_whitelisted_url` first.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import yaml

ROOT_DIR = Path(__file__).resolve().parent.parent  # /app/backend
CONFIG_DIR = ROOT_DIR / "config"
DATA_DIR = ROOT_DIR / "data"
INDEX_DIR = DATA_DIR / "index"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"

# Public type aliases.
SourceMeta = Dict[str, str]
SchemeMeta = Dict[str, object]


class ConfigError(RuntimeError):
    """Raised when the loaded configuration violates the closed-corpus contract."""


@dataclass(frozen=True)
class Scheme:
    id: str
    name: str
    category: str
    aliases: Tuple[str, ...]
    url: str
    doc_type: str


@dataclass(frozen=True)
class SourcesConfig:
    amc_id: str
    amc_name: str
    amc_full_name: str
    schemes: Tuple[Scheme, ...]

    @property
    def urls(self) -> Tuple[str, ...]:
        return tuple(s.url for s in self.schemes)

    def get_scheme(self, scheme_id: str) -> Optional[Scheme]:
        for s in self.schemes:
            if s.id == scheme_id:
                return s
        return None

    def scheme_by_url(self, url: str) -> Optional[Scheme]:
        for s in self.schemes:
            if s.url == url:
                return s
        return None


@dataclass(frozen=True)
class RefusalIntent:
    id: str
    description: str
    patterns: Tuple[str, ...]
    response: str


@dataclass(frozen=True)
class RefusalConfig:
    intents: Tuple[RefusalIntent, ...]
    dont_know_without_link: str
    pii_block: str
    banned_tokens: Tuple[str, ...]
    fallback_scheme_id: str
    greeting: str = ""
    conversational_ack: str = ""


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        raise ConfigError(f"Config file missing: {path}")
    with path.open("r", encoding="utf-8") as fh:
        try:
            return yaml.safe_load(fh) or {}
        except yaml.YAMLError as exc:  # pragma: no cover - hard fail
            raise ConfigError(f"YAML parse error in {path}: {exc}") from exc


@lru_cache(maxsize=1)
def load_sources(config_path: Optional[str] = None) -> SourcesConfig:
    """Load + validate sources.yaml. Cached for the life of the process."""
    path = Path(config_path) if config_path else CONFIG_DIR / "sources.yaml"
    raw = _read_yaml(path)

    amc = raw.get("amc") or {}
    if not amc.get("id") or not amc.get("name"):
        raise ConfigError("sources.yaml: amc.id and amc.name are required")

    schemes_raw = raw.get("schemes") or []
    expected = int(raw.get("expected_url_count", 5))

    schemes: List[Scheme] = []
    seen_ids: set = set()
    seen_urls: set = set()
    for entry in schemes_raw:
        sid = (entry or {}).get("id")
        sname = (entry or {}).get("name")
        category = (entry or {}).get("category") or ""
        aliases = tuple((entry or {}).get("aliases") or [])
        sources = (entry or {}).get("sources") or []
        if not sid or not sname:
            raise ConfigError("Each scheme must have id and name")
        if sid in seen_ids:
            raise ConfigError(f"Duplicate scheme id: {sid}")
        if not sources:
            raise ConfigError(f"Scheme {sid} has no sources")
        if len(sources) != 1:
            raise ConfigError(
                f"Scheme {sid} must have exactly one Groww source URL (got {len(sources)})"
            )
        src = sources[0] or {}
        url = src.get("url")
        if not url:
            raise ConfigError(f"Scheme {sid} missing source url")
        if url in seen_urls:
            raise ConfigError(f"Duplicate URL across schemes: {url}")
        if "groww.in/mutual-funds/" not in url:
            raise ConfigError(
                f"Scheme {sid}: url must be a groww.in mutual-fund product page (got {url})"
            )
        seen_ids.add(sid)
        seen_urls.add(url)
        schemes.append(
            Scheme(
                id=sid,
                name=sname,
                category=category,
                aliases=aliases,
                url=url,
                doc_type=src.get("doc_type", "Product_Page"),
            )
        )

    if len(schemes) != expected:
        raise ConfigError(
            f"sources.yaml must contain exactly {expected} schemes, found {len(schemes)}"
        )

    return SourcesConfig(
        amc_id=amc["id"],
        amc_name=amc["name"],
        amc_full_name=amc.get("full_name", amc["name"]),
        schemes=tuple(schemes),
    )


@lru_cache(maxsize=1)
def load_refusals(config_path: Optional[str] = None) -> RefusalConfig:
    path = Path(config_path) if config_path else CONFIG_DIR / "refusal_intents.yaml"
    raw = _read_yaml(path)
    intents_raw = raw.get("intents") or []
    intents = tuple(
        RefusalIntent(
            id=str(i.get("id", "")),
            description=str(i.get("description", "")),
            patterns=tuple(i.get("patterns", []) or []),
            response=str(i.get("response", "")).strip(),
        )
        for i in intents_raw
    )
    return RefusalConfig(
        intents=intents,
        dont_know_without_link=str(raw.get("dont_know_without_link", "")).strip(),
        pii_block=str(raw.get("pii_block", "")).strip(),
        banned_tokens=tuple(raw.get("banned_tokens", []) or []),
        fallback_scheme_id=str(raw.get("fallback_scheme_id", "")),
        greeting=str(raw.get("greeting", "")).strip(),
        conversational_ack=str(raw.get("conversational_ack", "")).strip(),
    )


def load_disclaimer(config_path: Optional[str] = None) -> str:
    path = Path(config_path) if config_path else CONFIG_DIR / "disclaimer.txt"
    if not path.exists():
        return "Facts-only. No investment advice."
    return path.read_text(encoding="utf-8").strip() or "Facts-only. No investment advice."


def ensure_dirs() -> None:
    """Make sure data directories exist."""
    for d in (RAW_DIR, PROCESSED_DIR, INDEX_DIR):
        d.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Whitelist helpers — used by the post-processor and CI gate.
# ---------------------------------------------------------------------------

_URL_RE = re.compile(r"https?://[^\s)\]\>\"']+")


def is_whitelisted_url(url: str) -> bool:
    cfg = load_sources()
    return url in cfg.urls


def extract_urls(text: str) -> List[str]:
    return _URL_RE.findall(text or "")


def whitelisted_urls() -> Sequence[str]:
    return load_sources().urls
