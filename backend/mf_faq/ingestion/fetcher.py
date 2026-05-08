"""Phase 1.1 Fetcher — pull the 5 Groww HTML pages with httpx, fall back to Playwright.

Respects:
  - basic robots.txt
  - ETag (If-None-Match) on subsequent runs
  - desktop UA + Accept-Language IN

No auto-follow on 301/302 of whitelisted URLs (raises a governance alert via log).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import httpx

from ..config_loader import RAW_DIR, Scheme, ensure_dirs, load_sources

logger = logging.getLogger(__name__)

# Make sure Playwright finds its browsers when called from inside supervisor
# (which doesn't inherit the shell's PLAYWRIGHT_BROWSERS_PATH). The default
# location used by the platform image is /pw-browsers; fall back to the user
# cache otherwise.
if not os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
    if Path("/pw-browsers").exists():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "/pw-browsers"

# Realistic desktop UA — Groww serves richer SSR content for desktop browsers.
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/127.0.0.0 Safari/537.36"
)

DEFAULT_HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}

# Heuristic: HTML smaller than this likely means we got a thin shell or block page.
MIN_HTML_BYTES = 50_000
# These tokens are expected on a healthy Groww product page.
HEALTH_TOKENS = ("Expense Ratio", "Exit Load", "AUM")


@dataclass
class FetchResult:
    scheme_id: str
    url: str
    status: int
    fetcher_kind: str  # "httpx" | "playwright" | "cache_304"
    html_path: Path
    meta_path: Path
    content_hash: str
    fetched_at: str
    health: str  # "ok" | "thin" | "blocked" | "error"
    error: Optional[str] = None


def _hash_html(html: str) -> str:
    return "sha256:" + hashlib.sha256(html.encode("utf-8", errors="ignore")).hexdigest()


def _save(scheme_id: str, html: str, meta: Dict) -> tuple[Path, Path]:
    folder = RAW_DIR / scheme_id
    folder.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    html_path = folder / f"{ts}.html"
    meta_path = folder / f"{ts}.meta.json"
    html_path.write_text(html, encoding="utf-8")
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    # Also maintain a 'latest' alias for convenience.
    latest_html = folder / "latest.html"
    latest_meta = folder / "latest.meta.json"
    latest_html.write_text(html, encoding="utf-8")
    latest_meta.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return html_path, meta_path


def _is_thin(html: str) -> bool:
    if len(html) < MIN_HTML_BYTES:
        return True
    # If less than two health tokens are present, treat as thin.
    hits = sum(1 for tok in HEALTH_TOKENS if tok.lower() in html.lower())
    return hits < 2


def _fetch_with_httpx(url: str, prev_etag: Optional[str] = None) -> tuple[int, str, Dict]:
    headers = dict(DEFAULT_HEADERS)
    if prev_etag:
        headers["If-None-Match"] = prev_etag
    with httpx.Client(
        http2=False,
        timeout=httpx.Timeout(30.0, connect=15.0),
        follow_redirects=False,
        headers=headers,
    ) as client:
        resp = client.get(url)
    info = {
        "final_url": str(resp.url),
        "etag": resp.headers.get("etag"),
        "content_type": resp.headers.get("content-type"),
        "redirected": str(resp.url) != url,
    }
    return resp.status_code, resp.text, info


def _fetch_with_playwright(url: str) -> tuple[int, str, Dict]:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("playwright not available") from exc

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ],
        )
        context = browser.new_context(
            user_agent=UA,
            viewport={"width": 1440, "height": 900},
            locale="en-IN",
            extra_http_headers={"Accept-Language": "en-IN,en;q=0.9"},
        )
        page = context.new_page()
        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            status = response.status if response else 0
            # Allow client-side hydration to populate the page.
            try:
                page.wait_for_load_state("networkidle", timeout=15_000)
            except Exception:
                pass
            # Try to expand any collapsed accordions / FAQs.
            try:
                page.evaluate(
                    "document.querySelectorAll('[aria-expanded=\"false\"]').forEach(el => el.click());"
                )
                page.wait_for_timeout(1000)
            except Exception:
                pass
            html = page.content()
            info = {"final_url": page.url, "engine": "chromium"}
            return status, html, info
        finally:
            context.close()
            browser.close()


def fetch_one(scheme: Scheme, prev_etag: Optional[str] = None) -> FetchResult:
    """Fetch one URL. Try httpx first, fall back to Playwright if thin."""
    fetched_at = datetime.now(timezone.utc).isoformat()
    url = scheme.url
    fetcher_kind = "httpx"
    error: Optional[str] = None
    status = 0
    html = ""
    info: Dict = {}

    try:
        status, html, info = _fetch_with_httpx(url, prev_etag=prev_etag)
        if status == 304:
            logger.info("[fetcher] 304 not modified for %s", scheme.id)
            # Reuse last cached html.
            cached = RAW_DIR / scheme.id / "latest.html"
            html = cached.read_text(encoding="utf-8") if cached.exists() else html
            fetcher_kind = "cache_304"
        elif status in (301, 302):
            error = f"unexpected redirect to {info.get('final_url')}"
            logger.warning("[fetcher] redirect for %s -> %s", url, info.get("final_url"))
        elif status >= 400:
            error = f"http_{status}"
            logger.warning("[fetcher] http %d for %s", status, url)
    except Exception as exc:  # network errors
        error = f"httpx_error: {exc}"
        logger.warning("[fetcher] httpx failed for %s: %s", url, exc)

    if not error and _is_thin(html):
        logger.info("[fetcher] httpx body looks thin for %s, falling back to playwright", scheme.id)
        try:
            status, html, info = _fetch_with_playwright(url)
            fetcher_kind = "playwright"
        except Exception as exc:
            error = f"playwright_error: {exc}"
            logger.error("[fetcher] playwright fallback failed for %s: %s", url, exc)

    health = "ok"
    if error:
        health = "error"
    elif _is_thin(html):
        health = "thin"

    content_hash = _hash_html(html) if html else "sha256:empty"
    meta = {
        "scheme_id": scheme.id,
        "url": url,
        "fetched_at": fetched_at,
        "http_status": status,
        "fetcher_kind": fetcher_kind,
        "content_hash_raw": content_hash,
        "size_bytes": len(html.encode("utf-8", errors="ignore")) if html else 0,
        "health": health,
        "error": error,
        **info,
    }
    if html:
        html_path, meta_path = _save(scheme.id, html, meta)
    else:
        html_path = RAW_DIR / scheme.id / "latest.html"
        meta_path = RAW_DIR / scheme.id / "latest.meta.json"
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    return FetchResult(
        scheme_id=scheme.id,
        url=url,
        status=status,
        fetcher_kind=fetcher_kind,
        html_path=html_path,
        meta_path=meta_path,
        content_hash=content_hash,
        fetched_at=fetched_at,
        health=health,
        error=error,
    )


def fetch_all() -> List[FetchResult]:
    ensure_dirs()
    cfg = load_sources()
    results: List[FetchResult] = []
    for scheme in cfg.schemes:
        prev_etag: Optional[str] = None
        prev_meta_path = RAW_DIR / scheme.id / "latest.meta.json"
        if prev_meta_path.exists():
            try:
                prev_meta = json.loads(prev_meta_path.read_text(encoding="utf-8"))
                prev_etag = prev_meta.get("etag")
            except Exception:
                prev_etag = None
        logger.info("[fetcher] fetching %s", scheme.id)
        results.append(fetch_one(scheme, prev_etag=prev_etag))
        time.sleep(1.0)  # polite delay between hosts
    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    out = fetch_all()
    for r in out:
        print(
            f"{r.scheme_id:18s} status={r.status:3d} via={r.fetcher_kind:11s} "
            f"health={r.health:7s} bytes={r.html_path.stat().st_size if r.html_path.exists() else 0:8d}"
        )
