# plan.md — Mutual Fund FAQ Assistant (Facts‑Only RAG)

## 1) Objectives
- Confirm the **end-to-end system is production-ready** after Phase 0–5 completion: ingestion refresh → index build → API → UI.
- Maintain **closed-corpus governance**: only the 5 whitelisted Groww URLs are ingested/cited; CI must fail on any out-of-whitelist URL.
- Maintain **facts-only, compliance-first responses**:
  - Factual answers: **≤ 3 sentences**, **exactly 1 citation link**, and footer **“Last updated from sources: <date>”**.
  - Refusals (advice/comparison/prediction/out-of-corpus walkthrough): polite, facts-only limitation, **exactly 1 whitelisted URL**.
  - PII or “don’t know”: **0 URLs**.
- Verify **scheduler correctness**: GitHub Actions refresh runs at **10:00 AM IST (04:30 UTC)** and uploads artifacts.
- Final deliverable quality: documentation, reproducibility, and a clean demo UX.

---

## 2) Implementation Steps

### Phase 1 — Core POC (Isolation) ✅ *Green*
**Goal:** A deterministic POC in `/app/backend/tests/test_core.py` that validates scraping + indexing + retrieval + guardrails.

✅ Completed components
1. **Governance scaffolding (Phase 0 deliverables)**
   - Folder structure + `config/sources.yaml` (exactly 5 URLs) + `refusal_intents.yaml` + `disclaimer.txt`.
   - `mf_faq/config_loader.py` strict validation (hard-fail if URLs differ / count != 5).

2. **Ingestion subphases (1.1–1.7) implemented and runnable**
   - **1.1 Fetcher**: `httpx` primary; **Playwright fallback** for thin/blocked HTML; writes `data/raw/*` + meta.
   - **1.2 Extractor**: trafilatura/BS4 + **fundDetails widget extraction** + derived riskometer/benchmark.
   - **1.3 Cleaner**: boilerplate stripping, NFKC normalization, currency normalization, drop FAQs, trim bios/contacts.
   - **1.4 Chunker**: section → chunk default; split only long sections; preserve numeric facts.
   - **1.5 Embedder**: **local `BAAI/bge-small-en-v1.5` (384-dim)** via sentence-transformers (The API does not support OpenAI embeddings).
   - **1.6 Indexer**: **ChromaDB persisted** + BM25 + `manifest.json` + atomic swap.
   - **1.7 Pipeline**: refresh orchestrator with drift detection + freeze behavior + refresh logs.

3. **Retrieval stack (Phase 2 logic used in POC)**
   - Normalizer + scheme resolver.
   - Hybrid: Chroma dense + BM25 → RRF fusion; **section-hint boost**.
   - Rerank: **`cross-encoder/ms-marco-MiniLM-L-6-v2`** (smaller CPU-friendly reranker).
   - Confidence gate: **absolute score OR margin**.

4. **Orchestrator core (Phase 3 logic used in POC)**
   - PII guard (PAN/Aadhaar/email/phone/OTP/account) → hard block → **0 URLs**.
   - Intent classifier: substring patterns + **regex fallbacks** (prediction/comparison shapes).
   - Refusal composer: **exactly 1 whitelisted URL**.
   - Generator: extractive default + Groq path (auto-active with `GROQ_API_KEY`).
   - Post-processor: ≤3 sentences, URL whitelist enforcement, banned-token enforcement, footer date.

5. **POC assertions**
   - All core tests pass; refresh outcome allows `ok|partial|frozen` because freeze preserves a healthy index.

**User stories (Phase 1)** ✅
1. One-command refresh builds or preserves a healthy index.
2. Factual query returns compliant answer with 1 whitelisted link.
3. PAN/PII blocks with 0 links.
4. Advice query refused with 1 whitelisted link.
5. Low-evidence query returns “don’t know” with 0 links.

---

### Phase 2 — V1 App Development (Backend + Frontend MVP) ✅ *Shipped*
**Goal:** Wrap the proven core into a usable app (no auth).

✅ Completed
1. **FastAPI backend (`/app/backend/server.py`)**
   - Routes: `/api/health`, `/api/meta`, `/api/examples`, `/api/ask`, `/api/reingest`, `/api/refresh-status`.
   - Also retains template routes: `/api/status`.
   - Background reingest job triggers `pipeline.refresh()`; orchestrator reload after refresh.
   - Structured logs with **query hashing** (no raw query storage).

2. **Groq wiring (inactive unless key is set)**
   - Auto-detection: `GROQ_API_KEY` enables Groq body rewrite; otherwise extractive.
   - URL policy enforced after generation.

3. **React dark-theme UI (minimal SPA)**
   - Always-visible disclaimer banner.
   - Welcome + 3 clickable example questions.
   - Chat view with intent badge, answer body, Source link, and footer date.
   - Sidebar scheme chips + meta panel + Re-ingest button.

4. **Manual end-to-end smoke test**
   - Backend + frontend verified via API calls and UI flow.

**User stories (Phase 2)** ✅
1. Ask factual scheme question → ≤3 sentences + exactly 1 source link + footer.
2. Disclaimer always visible.
3. Click example question to submit.
4. Advice/comparison/prediction refused.
5. Operator can trigger re-ingest and see status.

---

### Phase 3 — Scheduler + Evaluation + Compliance Gates ✅ *Completed*
**Goal:** Keep corpus fresh and prevent regressions.

✅ Completed
1. **GitHub Actions scheduler**
   - `.github/workflows/ingest.yml` with cron **`30 4 * * *`** (10:00 AM IST) + `workflow_dispatch`.
   - Runs refresh + core POC + compliance suite and uploads index artifacts.

2. **Eval + CI compliance**
   - `backend/tests/test_eval.py` compliance gate:
     - factual 17/17
     - refusal 10/10
     - pii 5/5
     - dont_know 2/2
     - Total 34/34 pass.

**User stories (Phase 3)** ✅
1. Daily refresh at 10:00 AM IST.
2. Manual workflow_dispatch refresh.
3. CI fails on non-whitelisted URL.
4. CI fails if >3 sentences.
5. CI fails if PII not blocked.

---

### Phase 4 — Polish + Deployment Readiness ✅ *Completed*
**Goal:** Make it easy to run, verify, and deploy.

✅ Completed
1. README includes setup, architecture, scheduler, limitations.
2. `.env.example` includes Groq keys (optional) and confidence config.
3. `docs/architecture.md` updated to match real extraction + retrieval realities.

**User stories (Phase 4)** ✅
1. New developer can run locally with clear steps.
2. Answer format and citation are consistent.
3. Performance/returns queries are refused.
4. `/api/meta` reports freshness.

---

## 3) Next Actions (Immediate)

### Phase 6 — Final End-to-End Testing + Delivery (Next)
**Goal:** Validate the full system with automated E2E testing and produce final handoff.

1. **E2E testing (testing_agent_v3)**
   - Run against the deployed preview:
     - Factual queries across all 5 schemes (expense ratio, AUM, NAV, min SIP, exit load, lock-in, riskometer, fund manager).
     - Refusal queries (advisory/comparison/prediction).
     - PII probes (PAN/Aadhaar/email/phone/OTP/account).
     - Off-corpus queries → dont_know path with 0 URLs.
   - Validate UI behavior:
     - Example chips work.
     - Loading states and error handling.
     - Citation link rendering (noopener/nofollow).
     - Re-ingest triggers refresh-status updates.

2. **Fix any E2E issues**
   - Retrieval mismatches → adjust section hints/normalization.
   - Extraction drift → update selectors and stable hash logic.
   - Any policy violation → tighten post-processor gate.

3. **Final delivery checklist**
   - Ensure GitHub Actions schedule is correct at 10:00 AM IST.
   - Ensure `.env.example` and README are consistent with final behavior.
   - Confirm corpus is still exactly 5 URLs and CI gate passes.

---

## 4) Success Criteria
- **All tests green:**
  - `python -m tests.test_core` passes.
  - `python -m tests.test_eval` passes (34/34).
- **Closed corpus enforced:** every cited URL equals one of the 5 in `sources.yaml`.
- **Strict output compliance:**
  - factual: ≤3 sentences, exactly 1 citation, footer date present.
  - refusal: exactly 1 citation.
  - pii/dont_know: 0 URLs.
- **E2E validated:** UI + API flows verified under testing_agent_v3.
- **Scheduler validated:** GitHub Actions configured for **10:00 AM IST / 04:30 UTC** and produces artifacts.
