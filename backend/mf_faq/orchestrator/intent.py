"""Intent classifier — conversational-aware, with greeting/ack/chitchat handling.

Intent taxonomy:
  factual        → proceed to retrieval
  advisory       → soft refusal
  comparison     → soft refusal
  prediction     → soft refusal
  capital_gains  → soft refusal
  greeting       → warm welcome (no retrieval)
  conversational → acknowledge + suggest (no retrieval)
  dont_know      → off-topic / PII request (graceful fallback)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from ..config_loader import RefusalIntent, load_refusals

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

_PREDICTION_REGEXES = (
    re.compile(r"\bwill\b[\s\S]{0,80}\b(give|return|grow|fetch|earn|generate|reach)\b"),
    re.compile(r"\bgive\b[\s\S]{0,40}%"),
    re.compile(r"\b\d+\s*%[\s\S]{0,15}returns?\b"),
    re.compile(r"\bwill\b[\s\S]{0,40}\bnav\b"),
    re.compile(r"\bhow much[\s\S]{0,30}\b(return|profit|grow|gain)\b"),
    # Hypothetical investment calculations.
    re.compile(r"\bif\s+i\s+(had\s+)?invest(ed)?\b", re.IGNORECASE),
    re.compile(r"\bwould\s+have\s+invest(ed)?\b", re.IGNORECASE),
    re.compile(r"\breturns?\s+for\s+(last\s+)?\d+\s*(year|month|yr)\b", re.IGNORECASE),
    re.compile(r"\binvest(ed)?\s+[\u20b9₹]?\s*\d{3,}\b", re.IGNORECASE),
    re.compile(r"\b\d{3,}\s*(rs|rupees|inr|₹)[\s\S]{0,30}\breturn\b", re.IGNORECASE),
    re.compile(r"\bhow\s+much\s+would\b", re.IGNORECASE),
    re.compile(r"\bwhat\s+would\s+(i|my|it)\b[\s\S]{0,30}\b(get|have|become|grow)\b", re.IGNORECASE),
    re.compile(r"\bcalculat\w*\s+(my\s+)?return\b", re.IGNORECASE),
    re.compile(r"\b(sip|lumpsum|lump\s*sum)\s+(return|calculator)\b", re.IGNORECASE),
    re.compile(r"\bwhat\s+(are|is)\s+the\s+returns?\b", re.IGNORECASE),
    re.compile(r"\bmaturity\s+(amount|value)\b", re.IGNORECASE),
    re.compile(r"\bwould\s+(it|have)\s+become\b", re.IGNORECASE),
    re.compile(r"\b(absolute|annualized|total)\s+return\b", re.IGNORECASE),
)

_COMPARISON_REGEXES = (
    re.compile(r"\b(vs|versus)\b"),
    re.compile(r"\bbetter than\b"),
    re.compile(r"\bcompared? to\b"),
)

# Greetings — respond warmly, no retrieval needed.
_GREETING_PATTERNS = (
    re.compile(r"^\s*(hi|hello|hey|yo|hiya|sup|howdy)\s*[!.?]*\s*$", re.IGNORECASE),
    re.compile(r"^\s*good\s*(morning|evening|afternoon|night)\s*[!.?]*\s*$", re.IGNORECASE),
)

# Conversational acknowledgments — "okay", "thanks", "got it", "interesting"
_CONVERSATIONAL_PATTERNS = (
    re.compile(r"^\s*(okay|ok|cool|nice|great|got it|understood|alright|sure)\s*[!.?]*\s*$", re.IGNORECASE),
    re.compile(r"^\s*(thanks|thank you|thank u|thx|ty)\s*[!.?]*\s*$", re.IGNORECASE),
    re.compile(r"^\s*(hmm|hm+|interesting|i see|ah|oh|wow)\s*[!.?]*\s*$", re.IGNORECASE),
)

# Self-referential / meta questions.
_SELF_REF_PATTERNS = (
    re.compile(r"\bwho\s+are\s+you\b", re.IGNORECASE),
    re.compile(r"\bwhat\s+are\s+you\b", re.IGNORECASE),
    re.compile(r"\bwhat\s+is\s+your\s+(name|purpose)\b", re.IGNORECASE),
    re.compile(r"\btell\s+me\s+about\s+(yourself|you)\b", re.IGNORECASE),
    re.compile(r"\bhow\s+are\s+you\b", re.IGNORECASE),
    re.compile(r"\bwhat\s+can\s+you\s+do\b", re.IGNORECASE),
)

# PII requests (not providing PII, but asking for it).
_PII_REQUEST_PATTERNS = (
    re.compile(r"\b(send|give|share|tell)\s+(me\s+)?(your|my|his|her|their)\s+(mobile|phone|email|address|pan|aadhaar|number)\b", re.IGNORECASE),
    re.compile(r"\b(your|my)\s+(mobile|phone|email|contact)\s*(number|address|id)?\b", re.IGNORECASE),
    re.compile(r"\bcall\s+me\b", re.IGNORECASE),
    re.compile(r"\bcontact\s+(me|details|info)\b", re.IGNORECASE),
)

# Completely off-topic.
_OFFTOPIC_PATTERNS = (
    re.compile(r"\b(weather|recipe|movie|song|joke|game|cricket|football|politics)\b", re.IGNORECASE),
    re.compile(r"\bhow\s+do\s+i\s+make\b", re.IGNORECASE),
    re.compile(r"\bhow\s+to\s+(cook|bake|drive|play)\b", re.IGNORECASE),
)


@dataclass
class IntentResult:
    label: str
    matched_intent: Optional[RefusalIntent] = None


def classify(query: str) -> IntentResult:
    if not query:
        return IntentResult(label="factual")
    q = query.lower().strip()
    cfg = load_refusals()

    # 0. Greetings → warm welcome.
    for r in _GREETING_PATTERNS:
        if r.search(q):
            return IntentResult(label="greeting")

    # 1. Conversational acks → acknowledge + suggest.
    for r in _CONVERSATIONAL_PATTERNS:
        if r.search(q):
            return IntentResult(label="conversational")

    # 2. Self-referential → friendly intro.
    for r in _SELF_REF_PATTERNS:
        if r.search(q):
            return IntentResult(label="greeting")

    # 3. PII requests → graceful decline.
    for r in _PII_REQUEST_PATTERNS:
        if r.search(q):
            return IntentResult(label="dont_know")

    # 4. Off-topic → soft redirect.
    for r in _OFFTOPIC_PATTERNS:
        if r.search(q):
            return IntentResult(label="dont_know")

    # 5. Refusal intents from config.
    priority = {"capital_gains_walkthrough": 0, "comparison": 1, "prediction": 2, "advisory": 3}
    matched: Optional[RefusalIntent] = None
    matched_priority = 99
    for intent in cfg.intents:
        if intent.id not in priority:
            continue
        for pat in intent.patterns:
            if pat.lower() in q:
                if priority[intent.id] < matched_priority:
                    matched = intent
                    matched_priority = priority[intent.id]
                break

    # Regex fallbacks.
    if matched is None or matched_priority > priority["prediction"]:
        for r in _PREDICTION_REGEXES:
            if r.search(q):
                pred = next((i for i in cfg.intents if i.id == "prediction"), None)
                if pred is not None:
                    matched = pred
                    matched_priority = priority["prediction"]
                    break
    if matched is None or matched_priority > priority["comparison"]:
        for r in _COMPARISON_REGEXES:
            if r.search(q):
                comp = next((i for i in cfg.intents if i.id == "comparison"), None)
                if comp is not None:
                    matched = comp
                    matched_priority = priority["comparison"]
                    break

    if matched:
        return IntentResult(label=matched.id, matched_intent=matched)
    return IntentResult(label="factual")
