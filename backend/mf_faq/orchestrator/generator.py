"""Generator — conversational Groq path with extractive fallback.

The Groq prompt is tuned for:
  - warm, concise, modern tone
  - no corporate-speak
  - strict fact-only compliance
  - ≤3 sentences
  - no URLs (appended by post-processor)
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import List, Optional

from ..retrieval.hybrid import RetrievedChunk

logger = logging.getLogger(__name__)

GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_TEMPERATURE = float(os.environ.get("GROQ_TEMPERATURE", "0.15"))
MAX_BODY_TOKENS = 200

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\u20b9\d])")


def _take_top_sentences(text: str, n: int = 3) -> str:
    parts = [p for p in _SENT_SPLIT.split(text or "") if p.strip()]
    if not parts:
        return text.strip()
    return " ".join(parts[:n]).strip()


def _extractive_body(query: str, top: RetrievedChunk) -> str:
    """Build a tight ~3-sentence factual body from the top chunk."""
    text = top.chunk.text.strip()
    section = top.chunk.section
    if section in ("Fund Details", "Riskometer", "Minimum Investments", "Fund Manager"):
        return text if len(text) < 300 else text[:300]
    sents = [p for p in _SENT_SPLIT.split(text) if p.strip()]
    if not sents:
        return text
    q_keywords = {w.lower() for w in re.findall(r"[a-zA-Z]+", query) if len(w) > 2}
    scored: List[tuple[float, str]] = []
    for s in sents:
        score = 0.0
        s_lower = s.lower()
        score += sum(1.0 for k in q_keywords if k in s_lower)
        if re.search(r"\d+\.?\d*%", s):
            score += 1.5
        if "₹" in s:
            score += 1.0
        scored.append((score, s))
    scored.sort(key=lambda x: x[0], reverse=True)
    top_sents = [s for _, s in scored[:3]]
    body = " ".join(top_sents).strip()
    if len(body) < 30:
        body = _take_top_sentences(text, 3)
    return body


@dataclass
class GeneratedBody:
    body: str
    used_groq: bool


# System prompt for conversational, compliant responses.
_SYSTEM_PROMPT = """\
You are a calm, knowledgeable mutual fund facts assistant for Groww.
Your personality: concise, warm, modern, professional. Never robotic.

RULES:
- Answer ONLY using the provided context passage.
- Maximum 3 short sentences. Lead with the direct answer.
- NEVER give investment advice, recommendations, comparisons, or predictions.
- NEVER include URLs, citations, or "Source:" lines — those are added separately.
- NEVER say "As an AI" or "I'm just a chatbot" or "Please provide".
- NEVER say "not specified in the given context" if the data IS present.
- If the context doesn't contain the answer, reply exactly: INSUFFICIENT_CONTEXT
- Use natural, conversational language. Avoid corporate jargon.
- Include specific numbers (%, ₹) when available in the context.

IMPORTANT: The context may use pipe-separated (|) or structured formats like:
  "NAV: 08 May '26 | ₹223.90 | Min. for SIP | ₹100 | Fund size (AUM) | ₹85,357.92 Cr | Expense ratio | 0.77%"
  "Min. for 1st investment ₹500 Min. for 2nd investment ₹500 Min. for SIP ₹500"
  "AK Amar Kalkundrikar Dec 2025 - Present"
These ARE valid data points. Parse the values from them and answer the question.

GOOD examples:
- "The expense ratio is 0.77% for the Direct Growth plan."
- "HDFC Mid Cap Fund carries a Very High risk rating on the SEBI riskometer."
- "There's a 1% exit load if you redeem within 1 year."
- "The minimum SIP amount is ₹500."
- "The fund is managed by Amar Kalkundrikar, who has been managing it since December 2025."

BAD examples:
- "Based on the available information, I can tell you that..."
- "The minimum SIP is not specified in the given context." (when it IS in the data)
- "As an AI assistant, I would like to inform you that..."
"""


def generate_body(
    query: str,
    top: RetrievedChunk,
    use_groq: Optional[bool] = None,
    extra_chunks: Optional[List[RetrievedChunk]] = None,
) -> GeneratedBody:
    """Return body only (no Source/footer).

    use_groq:
      - None  → auto: use Groq if GROQ_API_KEY is set, else extractive.
      - True  → force Groq (still falls back to extractive on failure).
      - False → extractive only.
    """
    extractive = _extractive_body(query, top)
    api_key = os.environ.get("GROQ_API_KEY")
    if use_groq is False or (use_groq is None and not api_key):
        return GeneratedBody(body=extractive, used_groq=False)
    if not api_key:
        return GeneratedBody(body=extractive, used_groq=False)
    try:
        from groq import Groq

        client = Groq(api_key=api_key)

        # Build context from top chunk + extra chunks for richer context.
        context_parts = [
            f"[Section: {top.chunk.section}]\n{top.chunk.text}"
        ]
        if extra_chunks:
            for ec in extra_chunks[:2]:
                if ec.chunk.chunk_id != top.chunk.chunk_id:
                    context_parts.append(
                        f"[Section: {ec.chunk.section}]\n{ec.chunk.text}"
                    )

        user_prompt = (
            f"User question: {query}\n\n"
            f"Context (scheme: {top.chunk.scheme_name}):\n"
            + "\n\n".join(context_parts)
            + "\n\nAnswer concisely:"
        )
        completion = client.chat.completions.create(
            model=GROQ_MODEL,
            temperature=GROQ_TEMPERATURE,
            max_tokens=MAX_BODY_TOKENS,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        )
        body = (completion.choices[0].message.content or "").strip()
        if not body or "INSUFFICIENT_CONTEXT" in body.upper():
            return GeneratedBody(body=extractive, used_groq=False)
        return GeneratedBody(body=body, used_groq=True)
    except Exception as exc:
        logger.warning("[generator] groq path failed: %s; falling back to extractive", exc)
        return GeneratedBody(body=extractive, used_groq=False)

