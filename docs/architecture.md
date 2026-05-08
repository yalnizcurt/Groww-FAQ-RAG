# Mutual Fund FAQ Assistant — Phase-wise Architecture

> Companion design doc for `docs/problemStatement.md`. Implementation lives in
> `/app/backend/mf_faq/` (ingestion, retrieval, orchestrator) and
> `/app/frontend/src/` (minimal React UI).
>
> **Disclaimer (used in UI and every refusal):** *Facts-only. No investment advice.*

## 1. Architectural principles

1. **Facts-over-Intelligence** — retrieval grounds every answer; the optional
   Groq generator only reformats retrieved facts. Default path is extractive.
2. **Single source of truth per answer** — exactly one citation URL per response.
3. **Closed corpus** — only the 5 whitelisted Groww URLs are ever ingested or
   cited; CI enforces this.
4. **Refusal by default** — advisory / opinion queries are deflected with a
   polite, educational redirect.
5. **PII-free** — no PAN, Aadhaar, account numbers, OTPs, emails, or phone
   numbers are processed. PII inputs are blocked with **zero URLs**.
6. **Determinism > Creativity** — low temperature, strict prompt contracts,
   hard answer-length caps (≤ 3 sentences).
7. **Auditability** — every response is traceable to a chunk, document URL, and
   "last updated" date.

## 2. Phases at a glance

| Phase | Outcome | Status |
|-------|---------|--------|
| 0 | Sources whitelisted, refusal taxonomy ready | ✅ |
| 1 | Corpus ingested + indexed (1.1 → 1.7) | ✅ |
| 2 | Hybrid retrieval + cross-encoder rerank | ✅ |
| 3 | Orchestrator + guardrails + extractive/Groq generator | ✅ |
| 4 | Minimal React UI wired end-to-end | ✅ |
| 5 | Eval suites + CI gates + observability | ✅ |

## 3. Phase 0 — Foundation & Governance

**Selected AMC:** HDFC Mutual Fund (HDFC Asset Management Company Ltd.)

**Selected schemes (5, category-diverse):**

| # | Scheme | Category | Source URL (Groww) |
|---|---|---|---|
| 1 | HDFC Mid Cap Fund — Direct Growth | Mid Cap | https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth |
| 2 | HDFC Equity Fund — Direct Growth | Flexi Cap | https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth |
| 3 | HDFC Focused Fund — Direct Growth | Focused | https://groww.in/mutual-funds/hdfc-focused-fund-direct-growth |
| 4 | HDFC ELSS Tax Saver — Direct Plan Growth | ELSS | https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth |
| 5 | HDFC Large Cap Fund — Direct Growth | Large Cap | https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth |

Configs (under `/app/backend/config/`):
- `sources.yaml` — exactly the 5 URLs above. `expected_url_count: 5` is enforced
  at startup; any drift is a hard error.
- `refusal_intents.yaml` — patterns + canned copy for advisory / comparison /
  prediction / capital-gains-walkthrough refusals.
- `disclaimer.txt` — the always-visible UI banner copy.

## 4. Phase 1 — Ingestion (offline)

```
URLs ─► 1.1 Fetcher ─► 1.2 Extractor ─► 1.3 Cleaner ─► 1.4 Chunker ─► 1.5 Embedder ─► 1.6 Indexer
                                                                                          │
                                                                              1.7 Refresh & Health
```

| Sub-phase | Responsibility | Module |
|---|---|---|
| 1.1 | Fetch the 5 Groww HTMLs (httpx → playwright fallback) | `mf_faq/ingestion/fetcher.py` |
| 1.2 | HTML → structured sections (trafilatura + BS4 selectors + `fundDetails_*` widget) | `mf_faq/ingestion/extractor.py` |
| 1.3 | NFKC + currency normalise + drop FAQs/manager bios/AMC contacts | `mf_faq/ingestion/cleaner.py` |
| 1.4 | Section-aware chunking (250-token soft cap, atomic numeric facts) | `mf_faq/ingestion/chunker.py` |
| 1.5 | `BAAI/bge-small-en-v1.5` (384-dim) via sentence-transformers | `mf_faq/ingestion/embedder.py` |
| 1.6 | ChromaDB (cosine) + `rank_bm25` + manifest.json (atomic swap) | `mf_faq/ingestion/indexer.py` |
| 1.7 | Refresh orchestrator with stable-hash drift detection + freeze | `mf_faq/ingestion/pipeline.py` |

**Why local embeddings?** The LLM API used for generation supports chat completions but lacks a compatible embeddings endpoint. We therefore embed locally with `bge-small-en-v1.5`. Vectors are deterministic, dimension is 384, and the model fits comfortably in CPU memory.

**Vector DB choice — ChromaDB.** Persistent on disk under
`backend/data/index/chroma/`. Cosine similarity. Atomic-swap pattern: build into
`.staging/`, then rename to live so readers never see a partial index.

**Scheduled refresh — GitHub Actions.** `.github/workflows/ingest.yml` runs the
pipeline at 10:00 AM IST (`30 4 * * *` UTC) and on `workflow_dispatch`.
The job uploads `data/index/*` as a workflow artifact so a deployed backend can
download the latest index without re-running the heavy pipeline.

## 5. Phase 2 — Retrieval

```
Query ─► normalize ─► scheme-resolve ─► hybrid (dense + BM25) ─► RRF fuse
        ─► section-hint boost ─► cross-encoder rerank ─► confidence gate
```

- `mf_faq/retrieval/normalizer.py` — NFKC, lowercase, MF acronym expansion.
- `mf_faq/retrieval/scheme_resolver.py` — longest substring match against scheme
  name + aliases.
- `mf_faq/retrieval/hybrid.py` — Chroma dense + BM25, RRF (K=60), with a small
  section-hint boost (+0.05 on RRF score) for keywords like "expense ratio →
  Fund Details" or "exit load → Exit Load and Tax".
- `mf_faq/retrieval/reranker.py` — `cross-encoder/ms-marco-MiniLM-L-6-v2`
  (~90MB CPU). Section boost is amplified 30× post-rerank so it actually moves
  rankings against cross-encoder logits.

**Confidence gate** uses *either* an absolute floor on the top-1 reranker score
*or* a margin (top1 − top2) above 0.5. The margin signal is the more reliable
"decisive selection" check on this corpus.

## 6. Phase 3 — Reasoning, Guardrails, Generation

`mf_faq/orchestrator/service.py` is the single entrypoint. URL policy:

| Situation | URLs in reply |
|---|---|
| **PII detected** | **0** — `pii_block` template only |
| **Insufficient evidence** / `dont_know` | **0** — `dont_know_without_link` only |
| **Refusal** (advisory / comparison / prediction / capital-gains) | **Exactly 1** matching Groww URL |
| **Successful factual** | **Exactly 1** whitelisted Groww URL |

Generator (`orchestrator/generator.py`):
- **Default — Extractive.** Pulls the top-1 chunk; for widget-style sections
  (Fund Details, Riskometer, Min Investments, Fund Manager) it returns the
  whole chunk; otherwise it picks the top 3 sentences scored by query keyword
  overlap and numeric-token density (`%`, `₹`, digits).
- **Optional — Groq** via OpenAI-compatible API (`pip install groq`). Auto-active
  when `GROQ_API_KEY` is set. Model = `llama-3.3-70b-versatile` (overridable).
  Returns body only; **Source: \<url\>** and **Last updated from sources: \<date\>**
  lines are appended deterministically by the post-processor.

Post-processor (`orchestrator/post_processor.py`) enforces:
- Sentence cap ≤ 3 on factual body.
- Strip any URLs that leaked into the body.
- Banned-token scan (`recommend`, `should invest`, `better than`, `will outperform`, …).
- URL whitelist (must be in `sources.yaml`).
- Footer date present on factual answers.

If any post-check fails on a factual draft → fall back to the safe `dont_know`
template with no URL.

## 7. Phase 4 — UI (React, dark theme)

Single-page chat layout (`frontend/src/App.js` + `App.css`):
- Header with brand + always-visible disclaimer pill.
- Sidebar: `/api/meta` panel (AMC, n_chunks, refresh date), covered-scheme
  chips (clickable), "Re-ingest now" button + last refresh status.
- Chat area: welcome card with 3 example questions (`/api/examples`), then
  user / assistant bubbles. Assistant bubble shows intent badge, body, citation
  link, and "Last updated from sources" footer.
- Composer: input + Ask button, disabled while loading. Submit on Enter.
- Footer: the corpus + retrieval stack tagline.

Coloring uses an "intent border" (green = facts, amber = refusal, blue =
don't-know, red = PII) so users can immediately see the *kind* of answer.

## 8. Phase 5 — Evaluation, Compliance, Observability

`backend/tests/test_eval.py` is the CI compliance gate. It runs four suites
(34 cases total):

| Suite | What it checks | Pass bar |
|---|---|---|
| factual (17) | Correct intent + whitelisted URL + footer + ≤3 sentences | ≥ 70 % |
| refusal (10) | Advisory / comparison / prediction / capital-gains routed correctly | 100 % |
| pii (5) | Inputs with PAN / Aadhaar / email / phone / OTP are blocked, **0 URLs** | 100 % |
| dont_know (2) | Off-corpus questions return safe template, **0 URLs** | 100 % |

Structured logs (server-side):
`{request_id, intent, scheme_id, chunk_ids, confidence, margin, latency_ms,
used_groq, query_hash, post_check_passed}`. The raw query is **never** stored —
only its SHA-256 hash for analytics.

## 9. Single-query data flow

```
User: "What is the exit load of HDFC Equity Fund?"
  ↓ POST /api/ask
PII guard            → clean
Intent classifier    → factual
Query normalize      → "what is the exit load of hdfc equity fund"
Scheme resolver      → scheme_id = hdfc_equity (auto-applied as Chroma filter)
Hybrid retrieve      → Chroma top-K + BM25 top-K → RRF fuse → top-10
Section-hint boost   → +0.05 on "Exit Load and Tax" chunks
Cross-encoder rerank → top-3 (with 30× section-boost amplification)
Confidence gate      → pass (margin > 0.5)
Generator            → extractive (Groq if key present)
Post-processor       → ≤3 sentences, +Source: <url>, +Last updated date
Response:
  "ELSS • 3Y Lock-in Equity ELSS Very High Risk
   Source: https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth
   Last updated from sources: 2026-05-08"
Logs (NO raw query): {request_id, intent=factual, scheme_id=hdfc_equity, ...}
```

## 10. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Groww updates a page → stale answer | Stable-content-hash diff in scheduled job; bump `last_updated` only on real change; freeze on multi-URL drift. |
| Groww blocks bot UAs | Realistic desktop UA + `If-None-Match` ETag + Playwright fallback for thin / blocked HTML. |
| Generator hallucinates a number | Extractive default; Groq path uses retrieved chunk as the only context with `INSUFFICIENT_CONTEXT` escape hatch. |
| Generator emits a non-whitelisted URL | Post-processor rejects + falls back to `dont_know`. |
| User asks for advice | Intent classifier (substring patterns + regex fallbacks) → polite refusal + 1 Groww URL. |
| User pastes PAN / Aadhaar / email / phone / OTP | PII guard rejects request before retrieval; never logged. |
| Ambiguous scheme name | Scheme resolver picks longest substring match; if no match, retrieval runs against the full corpus (still only the 5 whitelisted URLs). |
| Low-confidence retrieval | "I don't have a verified answer" with NO URL. |
| Fact only present in KIM/SID/AMC help | Same as above — out of scope this iteration. |

## 11. Alignment to problem statement

| Requirement | Where addressed |
|---|---|
| Curated corpus | Phase 0 — exactly 5 Groww HDFC URLs in `sources.yaml`. |
| 3–5 schemes, category diversity | Phase 0 — Mid Cap, Flexi Cap, Focused, ELSS, Large Cap. |
| ≤ 3 sentences, exactly 1 citation | Phase 3 post-processor. |
| Footer "Last updated from sources: …" | Phase 3 post-processor. |
| Refuse advisory queries with educational link | Phase 3 — link is the matching Groww scheme URL. |
| Welcome msg, 3 examples, visible disclaimer | Phase 4 UI. |
| No PII collection / storage | Phase 3 PII guard + Phase 5 query-hash logging. |
| Source restriction | Phase 0 + Phase 3 + Phase 5 CI gate. |
| Performance / return queries | Phase 3 prediction-intent refusal. |
| Accuracy + auditability | Phase 5 eval suites + structured PII-free logs. |
| Statement / capital-gains walkthrough (off-corpus) | Phase 3 — `capital_gains_walkthrough` refusal returns a Groww scheme link. |
