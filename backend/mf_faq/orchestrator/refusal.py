"""Refusal composer — polite refusal + exactly one whitelisted Groww URL."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..config_loader import Scheme, load_refusals, load_sources
from ..retrieval.scheme_resolver import resolve
@dataclass
class RefusalAnswer:
    body: str
    educational_url: str
    scheme_id: str
    intent_id: str


def compose_refusal(query: str, intent_id: str) -> RefusalAnswer:
    cfg_sources = load_sources()
    cfg_refusal = load_refusals()
    sm = resolve(query)
    if sm:
        scheme = sm.scheme
    else:
        fb_id = cfg_refusal.fallback_scheme_id or cfg_sources.schemes[0].id
        scheme = cfg_sources.get_scheme(fb_id) or cfg_sources.schemes[0]
        
    matched_intent = next((i for i in cfg_refusal.intents if i.id == intent_id), None)
    template = matched_intent.response if matched_intent else cfg_refusal.dont_know_without_link
    
    return RefusalAnswer(
        body=template,
        educational_url=scheme.url,
        scheme_id=scheme.id,
        intent_id=intent_id,
    )
