# Mutual Fund FAQ Assistant

A **facts-only**, source-cited Retrieval-Augmented Generation (RAG) assistant for
HDFC mutual fund schemes, using Groww product pages as the closed corpus.

> **Disclaimer:** Facts-only. No investment advice.

## Architecture

This project is a phase-wise implementation of the architecture in
[`docs/architecture.md`](./docs/architecture.md):

```
  GitHub Actions cron (10:00 AM IST)
          │
          ▼
  ┌── INGESTION (offline) ──────────────────────────┐
  │ 1.1 fetch (httpx → playwright fallback)             │
  │ 1.2 extract  (trafilatura + targeted selectors)     │
  │ 1.3 clean    (NFKC, currency, drop FAQs / bios)     │
  │ 1.4 chunk    (section-aware, atomic numeric facts)  │
  │ 1.5 embed    (BAAI/bge-small-en-v1.5, 384-dim)      │
  │ 1.6 index    (ChromaDB + rank_bm25 + manifest.json) │
  │ 1.7 refresh  (drift detection + freeze on multi-URL)│
  └────────────────────────────────────────────────┘
          │
          ▼
  ┌── RETRIEVAL (online) ───────────────────────────┐
  │ normalize → scheme-resolve → hybrid (dense + BM25)  │
  │ → RRF fuse → section-hint boost → cross-encoder    │
  │ rerank → confidence gate                            │
  └────────────────────────────────────────────────┘
          │
          ▼
  ┌── ORCHESTRATOR (online) ───────────────────────┐
  │ PII guard (PAN/Aadhaar/email/phone/OTP) → 0 URLs   │
  │ Intent classify (advisory/comparison/prediction)   │
  │   → polite refusal + 1 educational URL             │
  │ Factual: extractive OR Groq generator              │
  │   → post-processor: ≤3 sentences,                  │
  │     exactly 1 whitelisted URL, footer date         │
  └────────────────────────────────────────────────┘
          │
          ▼
        FastAPI /api/ask → React UI
```

## Selected AMC and schemes (Phase 0 — closed corpus)

The corpus is **strictly limited** to these 5 Groww product pages. The Phase 5
compliance gate fails the build if any answer cites a URL outside this list.

| # | Scheme | Category | URL |
|---|--------|----------|-----|
| 1 | HDFC Mid Cap Fund — Direct Growth | Mid Cap | https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth |
| 2 | HDFC Equity Fund — Direct Growth | Flexi Cap | https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth |
| 3 | HDFC Focused Fund — Direct Growth | Focused | https://groww.in/mutual-funds/hdfc-focused-fund-direct-growth |
| 4 | HDFC ELSS Tax Saver — Direct Plan Growth | ELSS | https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth |
| 5 | HDFC Large Cap Fund — Direct Growth | Large Cap | https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth |

## Setup (local)

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
# CPU-only torch keeps the install small
pip install --no-cache-dir torch==2.5.1 --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
python -m playwright install chromium
cp .env.example .env  # add GROQ_API_KEY here if you want LLM-rewritten answers
```

Build the index for the first time:

```bash
python -c "from mf_faq.ingestion.pipeline import refresh; print(refresh(force=True).to_dict())"
```

Run the API:

```bash
uvicorn server:app --host 0.0.0.0 --port 8001
```

### Frontend

```bash
cd frontend
yarn install
yarn start  # http://localhost:3000
```

## API

| Method | Path | Notes |
|---|---|---|
| GET | `/api/health` | Liveness + index status |
| GET | `/api/meta` | AMC, schemes, n_chunks, last refresh, embedder |
| GET | `/api/examples` | Three example factual questions |
| POST | `/api/ask` | `{ "query": "...", "use_groq": null }` → facts-only answer |
| POST | `/api/reingest` | Trigger pipeline refresh in background |
| GET | `/api/refresh-status` | Last refresh log entry |

## Tests

```bash
cd backend
python -m tests.test_core   # POC: ingestion + retrieval + orchestrator
python -m tests.test_eval   # Phase 5 compliance gate (factual + refusal + PII)
```

The `test_eval` suite is the **CI compliance gate**. It enforces:

- factual rate ≥ 70%,
- refusal/PII/don't-know rates = 100%,
- every cited URL is in `config/sources.yaml`,
- factual answers have ≤ 3 sentences,
- no banned advisory tokens ("recommend", "better than", …) in any answer.

## Scheduler

The `.github/workflows/ingest.yml` workflow refreshes the corpus daily at
**10:00 AM IST (04:30 UTC)** and uploads `data/index/*` as a build artifact.
Manual runs: **Actions → Refresh Mutual Fund FAQ Corpus → Run workflow**.

Local manual trigger:

```bash
curl -X POST http://localhost:8001/api/reingest
```

## Known limitations

- The corpus is **only** the 5 Groww product pages. Statement-download and
  capital-gains-report walkthroughs sit on AMC help pages that are *not* in
  the corpus, so the assistant returns *"I don't have a verified answer"*.
- Performance / return computations are deliberately refused (the assistant
  redirects to the official scheme page).
- The API key used for generation does **not** support OpenAI's `/v1/embeddings`
  endpoint, so embeddings run **locally** with `BAAI/bge-small-en-v1.5`.
- The Groq path is opt-in; without `GROQ_API_KEY` the system answers extractively
  (still source-cited and policy-compliant).
- Riskometer extraction relies on the Groww page surfacing a "X Risk" textual
  label — if Groww switches to image-only labels in the future, that section
  will degrade until the extractor is updated.

## Deployment

1. **Backend (Railway / Fly / any container host)** — set `MONGO_URL`,
   `DB_NAME`, `CORS_ORIGINS`, optional `GROQ_API_KEY`.
2. **Frontend (Vercel / Netlify)** — set `REACT_APP_BACKEND_URL`.
3. **GitHub Actions** — `.github/workflows/ingest.yml` refreshes the index on
   schedule. To persist the rebuilt index across runs, add a step that pushes
   `backend/data/index/` to a release branch or to object storage.
