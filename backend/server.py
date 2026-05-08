from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

from mf_faq.config_loader import (  # noqa: E402
    INDEX_DIR,
    Scheme,
    ensure_dirs,
    load_disclaimer,
    load_sources,
)
from mf_faq.ingestion.indexer import load_index  # noqa: E402
from mf_faq.ingestion.pipeline import RefreshResult, refresh  # noqa: E402
from mf_faq.orchestrator.service import Orchestrator, hash_query_for_logs  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("server")

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "mf_faq")
CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "*").split(",")

mongo_client = AsyncIOMotorClient(MONGO_URL, serverSelectionTimeoutMS=3000)
mongo_db = mongo_client[DB_NAME]

# ---------------------------------------------------------------------------
# Lifespan: load index + orchestrator at startup so first request is fast.
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_dirs()
    try:
        load_index()
        logger.info("index loaded at startup")
    except Exception as exc:
        logger.warning("index not yet built (%s) — use /api/reingest to build it", exc)
    try:
        # Pre-warm orchestrator (loads embedder + reranker if index present).
        orch = Orchestrator.get()
        try:
            orch._ensure_loaded()
            # Force the cross-encoder reranker to load NOW so the first /api/ask
            # request doesn't pay the model-download / model-load cost.
            from mf_faq.retrieval.reranker import Reranker
            Reranker.get()._load()
            logger.info("reranker pre-warmed at startup")
        except Exception as exc:
            logger.warning("reranker pre-warm failed: %s", exc)
    except Exception:
        pass
    yield
    mongo_client.close()


app = FastAPI(
    title="Mutual Fund FAQ Assistant",
    description="Facts-only RAG assistant for HDFC mutual fund schemes (Groww corpus).",
    version="0.2.0",
    lifespan=lifespan,
)

api_router = APIRouter(prefix="/api")

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class AskRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    session_id: Optional[str] = None
    use_groq: Optional[bool] = None


class AskResponse(BaseModel):
    answer: str
    body: str
    citation_url: Optional[str] = None
    last_updated: Optional[str] = None
    intent: str
    scheme_id: Optional[str] = None
    request_id: str
    used_groq: bool = False
    latency_ms: int
    confidence: float
    margin: float
    suggestions: List[str] = []


class SchemeInfo(BaseModel):
    id: str
    name: str
    category: str
    url: str


class MetaResponse(BaseModel):
    amc: str
    amc_full_name: str
    schemes: List[SchemeInfo]
    n_chunks: int
    last_refresh_at: Optional[str] = None
    last_refresh_outcome: Optional[str] = None
    embedder_model: Optional[str] = None
    disclaimer: str


class ExamplesResponse(BaseModel):
    examples: List[str]


class HealthResponse(BaseModel):
    status: str
    index_loaded: bool
    n_chunks: int
    schemes: int
    timestamp: str


class RefreshResponse(BaseModel):
    started_at: str
    finished_at: str
    outcome: str
    n_chunks: int
    drift_count: int
    error: Optional[str] = None
    per_scheme: dict


# ---------------------------------------------------------------------------
# Refresh state (in-memory; safe for single-process FastAPI worker).
# ---------------------------------------------------------------------------

_refresh_state = {
    "running": False,
    "last_started_at": None,
    "last_finished_at": None,
    "last_result": None,  # type: Optional[RefreshResult]
}


async def _run_refresh_async(force: bool, skip_fetch: bool) -> None:
    _refresh_state["running"] = True
    _refresh_state["last_started_at"] = datetime.now(timezone.utc).isoformat()
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, refresh, force, skip_fetch)
        _refresh_state["last_result"] = result
        _refresh_state["last_finished_at"] = result.finished_at
        # Reload orchestrator's cached index handle.
        try:
            Orchestrator.get().reload()
        except Exception:
            pass
        logger.info(
            "refresh complete outcome=%s n_chunks=%d drift=%d",
            result.outcome,
            result.n_chunks,
            result.drift_count,
        )
    except Exception as exc:
        logger.exception("refresh failed: %s", exc)
        _refresh_state["last_finished_at"] = datetime.now(timezone.utc).isoformat()
        _refresh_state["last_result"] = None
    finally:
        _refresh_state["running"] = False


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@api_router.get("/")
async def root():
    return {
        "service": "mf_faq",
        "version": app.version,
        "docs": "/api/meta",
    }


@api_router.get("/health", response_model=HealthResponse)
async def health():
    try:
        idx = load_index()
        return HealthResponse(
            status="ok",
            index_loaded=True,
            n_chunks=idx.n_chunks,
            schemes=len(load_sources().schemes),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    except Exception:
        return HealthResponse(
            status="degraded",
            index_loaded=False,
            n_chunks=0,
            schemes=len(load_sources().schemes),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )


@api_router.get("/meta", response_model=MetaResponse)
async def meta():
    cfg = load_sources()
    n_chunks = 0
    last_refresh_at = None
    last_refresh_outcome = None
    embedder_model = None
    try:
        idx = load_index()
        n_chunks = idx.n_chunks
        last_refresh_at = idx.manifest.get("built_at")
        embedder_model = idx.manifest.get("embedder", {}).get("model")
    except Exception:
        pass
    last = _refresh_state.get("last_result")
    if last is not None:
        last_refresh_outcome = last.outcome
        last_refresh_at = last.finished_at or last_refresh_at
    return MetaResponse(
        amc=cfg.amc_name,
        amc_full_name=cfg.amc_full_name,
        schemes=[
            SchemeInfo(id=s.id, name=s.name, category=s.category, url=s.url)
            for s in cfg.schemes
        ],
        n_chunks=n_chunks,
        last_refresh_at=last_refresh_at,
        last_refresh_outcome=last_refresh_outcome,
        embedder_model=embedder_model,
        disclaimer=load_disclaimer(),
    )


@api_router.get("/examples", response_model=ExamplesResponse)
async def examples():
    cfg = load_sources()
    s1 = cfg.schemes[0].name
    s2 = cfg.schemes[1].name
    s3 = cfg.schemes[3].name
    return ExamplesResponse(
        examples=[
            f"What is the expense ratio of {s1}?",
            f"What is the exit load of {s2}?",
            f"What is the lock-in period of {s3}?",
        ]
    )


@api_router.post("/ask", response_model=AskResponse)
async def ask(req: AskRequest, request: Request):
    if not (req.query or "").strip():
        raise HTTPException(status_code=400, detail="query is required")
    orch = Orchestrator.get()
    loop = asyncio.get_event_loop()
    res = await loop.run_in_executor(
        None,
        lambda: orch.ask(req.query, session_id=req.session_id, use_groq=req.use_groq),
    )
    # Structured log: NEVER store the raw query if it might contain PII.
    log_doc = {
        "request_id": res.request_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "intent": res.intent,
        "scheme_id": res.scheme_id,
        "chunk_ids": [c["chunk_id"] for c in res.top_chunks],
        "confidence": res.answer.confidence,
        "margin": res.margin,
        "latency_ms": res.latency_ms,
        "used_groq": res.used_groq,
        "query_hash": hash_query_for_logs(req.query),
        "post_check_passed": res.answer.post_check_passed,
    }
    try:
        await mongo_db.ask_logs.insert_one(log_doc)
    except Exception as exc:
        logger.warning("failed to log ask: %s", exc)
    logger.info(
        "ASK rid=%s intent=%s scheme=%s margin=%.2f conf=%.2f latency=%dms groq=%s",
        res.request_id,
        res.intent,
        res.scheme_id,
        res.margin,
        res.answer.confidence,
        res.latency_ms,
        res.used_groq,
    )
    return AskResponse(
        answer=res.answer.render(),
        body=res.answer.body,
        citation_url=res.answer.citation_url,
        last_updated=res.answer.last_updated,
        intent=res.intent,
        scheme_id=res.scheme_id,
        request_id=res.request_id,
        used_groq=res.used_groq,
        latency_ms=res.latency_ms,
        confidence=res.answer.confidence,
        margin=res.margin,
        suggestions=res.suggestions,
    )


@api_router.post("/reingest")
async def reingest_now(force: bool = True, skip_fetch: bool = False):
    if _refresh_state["running"]:
        return {"status": "already_running", "started_at": _refresh_state["last_started_at"]}
    asyncio.create_task(_run_refresh_async(force=force, skip_fetch=skip_fetch))
    return {
        "status": "started",
        "started_at": datetime.now(timezone.utc).isoformat(),
    }


@api_router.get("/refresh-status", response_model=Optional[RefreshResponse])
async def refresh_status() -> Optional[RefreshResponse]:
    last = _refresh_state.get("last_result")
    if last is None:
        return None
    return RefreshResponse(
        started_at=last.started_at,
        finished_at=last.finished_at,
        outcome=last.outcome,
        n_chunks=last.n_chunks,
        drift_count=last.drift_count,
        error=last.error,
        per_scheme=last.per_scheme,
    )


# Backwards-compat: keep the original /api/status routes from the template.
class StatusCheckCreate(BaseModel):
    client_name: str


class StatusCheck(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    client_name: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


@api_router.post("/status", response_model=StatusCheck)
async def create_status_check(input: StatusCheckCreate):
    obj = StatusCheck(client_name=input.client_name)
    doc = obj.model_dump()
    doc["timestamp"] = doc["timestamp"].isoformat()
    await mongo_db.status_checks.insert_one(doc)
    return obj


@api_router.get("/status", response_model=List[StatusCheck])
async def get_status_checks():
    rows = await mongo_db.status_checks.find({}, {"_id": 0}).to_list(100)
    out: List[StatusCheck] = []
    for r in rows:
        ts = r.get("timestamp")
        if isinstance(ts, str):
            r["timestamp"] = datetime.fromisoformat(ts)
        out.append(StatusCheck(**r))
    return out


app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)
