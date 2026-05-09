"""Semantic Router — LLM-based query understanding and capability inference.

Replaces hardcoded intent classification.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_TEMPERATURE = float(os.environ.get("GROQ_TEMPERATURE", "0.0"))

@dataclass
class SemanticIntent:
    capability: str
    metric: Optional[str] = None
    is_performance_query: bool = False
    is_pii: bool = False
    is_greeting: bool = False
    is_conversational: bool = False
    is_comparison: bool = False
    is_advisory: bool = False
    needs_clarification: bool = False
    confidence: float = 1.0


_ROUTER_PROMPT = """\
You are a semantic query parser for a mutual fund facts assistant.
Analyze the user's query and the conversational context.

Capabilities:
- fund_costs (expense ratio, exit load, fees)
- fund_risk (riskometer, volatility, risk)
- minimum_investment (SIP minimum, lumpsum minimum)
- fund_management (fund manager, launch date, AUM, inception)
- portfolio (sector allocation, holdings)
- factual (any other factual information about the fund)
- greeting (hi, hello, etc.)
- conversational (thanks, okay, got it, etc.)
- out_of_domain (off-topic queries)

Determine if the query falls into any special categories:
- is_performance_query: true if asking for historical returns, future returns, profit calculations, NAV history, "how much would I have", etc.
- is_pii: true if asking to contact, call, or requesting personal info.
- is_comparison: true if comparing two or more funds.
- is_advisory: true if asking for recommendations, advice, or "should I invest".

Output MUST be a valid JSON object matching this schema exactly:
{
  "capability": "<one of the capabilities above>",
  "metric": "<the specific metric requested, e.g., 'expense ratio', 'riskometer', or null>",
  "is_performance_query": <true/false>,
  "is_pii": <true/false>,
  "is_greeting": <true/false>,
  "is_conversational": <true/false>,
  "is_comparison": <true/false>,
  "is_advisory": <true/false>,
  "needs_clarification": <true/false, true if ambiguous or unclear>,
  "confidence": <float 0.0 to 1.0>
}
"""

def parse_query_semantically(query: str, last_scheme_name: Optional[str] = None, last_topic: Optional[str] = None) -> SemanticIntent:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        logger.warning("[semantic_router] GROQ_API_KEY not set. Using fallback intent logic.")
        return SemanticIntent(capability="factual")
    
    try:
        from groq import Groq
        client = Groq(api_key=api_key)
        
        user_prompt = f"User query: '{query}'\n"
        if last_scheme_name:
            user_prompt += f"Context (Previous scheme): '{last_scheme_name}'\n"
        if last_topic:
            user_prompt += f"Context (Previous topic): '{last_topic}'\n"
            
        completion = client.chat.completions.create(
            model=GROQ_MODEL,
            temperature=GROQ_TEMPERATURE,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _ROUTER_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        )
        
        content = completion.choices[0].message.content or "{}"
        data = json.loads(content)
        
        return SemanticIntent(
            capability=data.get("capability", "factual"),
            metric=data.get("metric"),
            is_performance_query=data.get("is_performance_query", False),
            is_pii=data.get("is_pii", False),
            is_greeting=data.get("is_greeting", False),
            is_conversational=data.get("is_conversational", False),
            is_comparison=data.get("is_comparison", False),
            is_advisory=data.get("is_advisory", False),
            needs_clarification=data.get("needs_clarification", False),
            confidence=float(data.get("confidence", 1.0))
        )
        
    except Exception as exc:
        logger.error("[semantic_router] Groq API failure: %s", exc)
        return SemanticIntent(capability="factual")
