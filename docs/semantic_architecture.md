# Groww Semantic Conversational Assistant Architecture

## 1. System Architecture

The redesigned RAG system transitions from a rigid, regex-based intent classification pipeline to a probabilistic, semantic orchestration layer powered by LLM routing and validation.

### Orchestration Flow
1. **Understand (Semantic Parser)**: The user query, along with conversational history (previous scheme, previous topic), is sent to a fast LLM (Groq Llama-3.3-70b-versatile) for semantic parsing.
2. **Infer (Capability Router)**: The parser infers the requested capability (e.g., `fund_costs`, `fund_risk`, `minimum_investment`, `performance_related`, `greeting`, `chitchat`, `out_of_domain`), the specific metric, ambiguity level, and compliance risk.
3. **Validate**: If the query is performance-related or requests unauthorized predictions, it triggers a compliance refusal. If it is ambiguous, it triggers a confidence-based clarification.
4. **Retrieve**: The inferred metric and scheme are used to query the hybrid retriever. 
5. **Verify (Field-level Validation)**: The retrieved chunks are validated against the inferred metric to ensure relevance (e.g., rejecting an exit load chunk when expense ratio was requested).
6. **Answer**: The verified chunks are sent to the generation module to produce a conversational, facts-only response.

## 2. Semantic Routing Design

Instead of hardcoded intents, queries are mapped to core capabilities:
- `fund_costs`: Expense ratio, exit load, tax implications.
- `fund_risk`: Riskometer, volatility.
- `minimum_investment`: SIP minimum, lumpsum minimum.
- `performance_related`: Historical returns, NAV history.
- `fund_management`: Fund manager, launch date.
- `portfolio`: Sector allocation, holdings.

### Semantic Parser Prompt
```text
You are a semantic query parser for a mutual fund RAG assistant.
Analyze the user query and the conversational context.
Output JSON with the following structure:
{
  "capability": "fund_costs|fund_risk|minimum_investment|performance_related|fund_management|portfolio|greeting|conversational|out_of_domain",
  "metric": "Specific metric requested, e.g., expense ratio, riskometer",
  "is_performance_query": true/false (true if asking about past returns, future returns, profit calculations),
  "is_pii": true/false,
  "confidence": 0.0-1.0 (how confident are you in understanding the user's intent),
  "needs_clarification": true/false
}
```

## 3. Confidence Scoring System

1. **Semantic Confidence**: The parser LLM provides an intent understanding score. Low confidence triggers a clarification request.
2. **Retrieval Confidence**: The cross-encoder reranker scores the relevance of the retrieved chunk. 
3. **Margin Confidence**: The difference between the top chunk score and the second chunk score.

## 4. Memory Design

The session context tracks:
- `last_scheme_id`
- `last_scheme_name`
- `last_metric`
- `last_intent`
This enables resolving queries like "What about risk?" by injecting the `last_scheme_name` into the semantic parsing step.

## 5. Retrieval Validation Logic

Field-level validation compares the retrieved chunk's `section` or `text` metadata against the parser's inferred `metric`.
If the capability is `fund_costs` and the metric is `expense ratio`, but the top retrieved chunk is about `SIP minimum`, the validation step fails, preventing hallucinatory or incorrect answers.

## 6. Frontend Interaction Patterns

- **Dynamic Suggestions**: Quick replies update contextually based on the `last_scheme` and `last_capability`.
- **Typing Indicators**: Visual feedback during the multi-step "Understand -> Infer -> Retrieve -> Answer" pipeline.
- **Compact Answer Cards**: Responses emphasize the specific metric (e.g., a bolded 0.77% expense ratio) with a clear citation link.
- **Trust Signals**: Explicit badges indicating "Data from Official Factsheet".
