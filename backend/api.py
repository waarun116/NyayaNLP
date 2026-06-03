"""
FastAPI Backend for NyayaNLP
Handles AI response generation and verification.
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

import logging
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from ollama import AsyncClient
from pydantic import BaseModel, Field, field_validator

from backend.core import settings
from backend.core.logging_config import configure_logging
from backend.core.response_guard import looks_like_system_error_response
from backend.models.llm_interface import chat_async, validate_model_name
from backend.verifier.improved_verifier import NyayaVerifier

configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    timeout = httpx.Timeout(
        connect=settings.OLLAMA_CONNECT_TIMEOUT,
        read=max(
            settings.OLLAMA_READ_TIMEOUT_MAX,
            settings.OLLAMA_READ_COMPLEX,
            settings.OLLAMA_READ_SIMPLE,
        ),
        write=120.0,
        pool=20.0,
    )
    app.state.ollama = AsyncClient(timeout=timeout)
    logger.info("Ollama AsyncClient ready (read timeout up to %ss)", timeout.read)
    try:
        yield
    finally:
        await app.state.ollama.aclose()
        logger.info("Ollama AsyncClient closed")


app = FastAPI(
    title="NyayaNLP API",
    description="AI Hallucination Detector with Nyaya Philosophy",
    version="2.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8000",
        "*",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

verifier = NyayaVerifier()


def _results_dir() -> Path:
    # backend/api.py -> nyay/backend/api.py so parents[1] is project root (nyay/)
    root = Path(__file__).resolve().parents[1]
    return root / "data" / "results"


def _safe_read_results_json(filename: str) -> Any:
    # Accept only simple filenames to avoid path traversal.
    if not filename or "/" in filename or "\\" in filename:
        raise ValueError("Invalid filename")
    allowed = filename.lower().endswith(".json")
    if not allowed:
        raise ValueError("Only .json files are allowed")

    base = _results_dir().resolve()
    target = (base / filename).resolve()
    if not str(target).startswith(str(base)):
        raise ValueError("Invalid path")
    if not target.exists():
        raise FileNotFoundError(filename)
    return json.loads(target.read_text(encoding="utf-8"))


def _infer_category(name: str) -> str:
    n = (name or "").lower()
    if n.startswith("ablation"):
        return "ablation"
    if n.startswith("self_consistency"):
        return "self_consistency"
    return "other"


# --- Request / response models ---


class GenerateRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=settings.MAX_QUESTION_CHARS)
    model: str = Field(default="llama3", max_length=settings.MAX_MODEL_NAME_LEN)

    @field_validator("question")
    @classmethod
    def strip_question(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("question cannot be empty or whitespace only")
        return s

    @field_validator("model")
    @classmethod
    def check_model(cls, v: str) -> str:
        return validate_model_name(v)


class GenerateResponse(BaseModel):
    question: str
    response: str
    model_used: str


class VerifyRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=settings.MAX_QUESTION_CHARS)
    response: str = Field(..., min_length=1, max_length=settings.MAX_RESPONSE_CHARS)
    model_used: Optional[str] = Field(default="llama3", max_length=settings.MAX_MODEL_NAME_LEN)

    @field_validator("question", "response")
    @classmethod
    def strip_text(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("field cannot be empty or whitespace only")
        return s

    @field_validator("model_used")
    @classmethod
    def check_model_used(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        return validate_model_name(v)


class ClaimResult(BaseModel):
    claim: str
    verified: bool
    confidence: float
    subject: str
    reason: str
    source_name: Optional[str] = None
    source_url: Optional[str] = None
    evidence_snippet: Optional[str] = None
    nyaya: Optional[dict] = None
    semantic_score: Optional[float] = None
    semantic_matched_text: Optional[str] = None
    semantic_threshold: Optional[float] = None
    lexical_score: Optional[float] = None
    combined_confidence_breakdown: Optional[dict] = None
    sources_used: Optional[List[str]] = None
    lexical_confidence: Optional[float] = None
    lexical_matches: Optional[float] = None
    lexical_total_terms: Optional[int] = None
    wikidata_value: Optional[str] = None
    wikidata_url: Optional[str] = None
    wikidata_property_id: Optional[str] = None
    wikidata_property_match: Optional[str] = None
    wikidata_evidence_text: Optional[str] = None
    duckduckgo_url: Optional[str] = None
    dbpedia_url: Optional[str] = None
    restcountries_url: Optional[str] = None
    restcountries_evidence_text: Optional[str] = None
    verdict_primary: Optional[str] = None
    verdict_secondary: Optional[str] = None
    freshness_checked_at: Optional[str] = None
    freshness_max_age_days: Optional[int] = None
    resolved_entity: Optional[str] = None
    resolved_attribute: Optional[str] = None
    match_category: Optional[str] = None
    evidence_location: Optional[str] = None
    evidence_sentence: Optional[str] = None


class VerifyResponse(BaseModel):
    question: str
    response: str
    model_used: str
    total_claims: int
    verified_claims: int
    accuracy: float
    verdict: str
    verdict_primary: Optional[str] = None
    verdict_secondary: Optional[str] = None
    verdict_explanation: Optional[str] = None
    nyaya_verdict: Optional[dict] = None
    hallucination_percent: float = 0.0
    hallucination_label: str = "No claims detected"
    nyaya_explainability: Optional[Dict[str, Any]] = None
    claims: List[ClaimResult]


class QueryRequest(BaseModel):
    """Legacy shape from earlier main.py (generate-only)."""

    question: str = Field(..., min_length=1, max_length=settings.MAX_QUESTION_CHARS)
    model: str = Field(default="llama3", max_length=settings.MAX_MODEL_NAME_LEN)

    @field_validator("question")
    @classmethod
    def strip_q(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("question cannot be empty")
        return s

    @field_validator("model")
    @classmethod
    def check_m(cls, v: str) -> str:
        return validate_model_name(v)


class QueryResponse(BaseModel):
    question: str
    answer: str
    model_used: str
    status: str


# --- Routes ---


@app.get("/")
async def root():
    return {
        "name": "NyayaNLP API",
        "version": "2.2.0",
        "status": "running",
        "description": "AI Hallucination Detector with Nyaya Philosophy",
        "docs": "/docs",
    }


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.post("/generate", response_model=GenerateResponse)
async def generate_response(request: GenerateRequest):
    """Generate AI response using Ollama HTTP API."""
    logger.info("Generate model=%s question_len=%s", request.model, len(request.question))
    text = await chat_async(
        app.state.ollama,
        request.model,
        request.question,
    )
    return GenerateResponse(
        question=request.question,
        response=text,
        model_used=request.model,
    )


@app.post("/query", response_model=QueryResponse)
async def query_legacy(request: QueryRequest):
    """Same as /generate but returns the legacy { answer, status } fields."""
    logger.info("Query (legacy) model=%s", request.model)
    text = await chat_async(app.state.ollama, request.model, request.question)
    err = text.startswith("Error:")
    return QueryResponse(
        question=request.question,
        answer=text,
        model_used=request.model,
        status="error" if err else "generated",
    )


@app.post("/verify", response_model=VerifyResponse)
async def verify_response(request: VerifyRequest):
    logger.info("Verify question_len=%s response_len=%s", len(request.question), len(request.response))
    try:
        if looks_like_system_error_response(request.response):
            return VerifyResponse(
                question=request.question,
                response=request.response,
                model_used=request.model_used or "llama3",
                total_claims=0,
                verified_claims=0,
                accuracy=0.0,
                verdict="NO_LLM_RESPONSE",
                nyaya_verdict={
                    "verdict": "Unassessable",
                    "english": "Unassessable",
                    "icon": "⛔",
                    "color": "#9E9E9E",
                    "description": "System error/output detected, not an LLM factual answer.",
                    "explanation": "Verification skipped to avoid treating runtime errors as hallucinations.",
                    "verified": 0,
                    "total": 0,
                },
                hallucination_percent=0.0,
                hallucination_label="Skipped (system/error response)",
                nyaya_explainability={
                    "dominant_level": "none",
                    "trust_index": 0.0,
                    "reasoning_chain": ["Response identified as system/error output.", "Claim verification intentionally skipped."],
                },
                claims=[],
            )
        result = verifier.verify_response_with_nyaya(request.question, request.response)
        claims = [
            ClaimResult(
                claim=c["claim"],
                verified=c["verified"],
                confidence=c["confidence"],
                subject=c.get("subject", "Unknown"),
                reason=c.get("reason", ""),
                source_name=c.get("source_name"),
                source_url=c.get("source_url"),
                evidence_snippet=c.get("evidence_snippet"),
                nyaya=c.get("nyaya", None),
                semantic_score=c.get("semantic_score"),
                semantic_matched_text=c.get("semantic_matched_text"),
                semantic_threshold=c.get("semantic_threshold"),
                lexical_score=c.get("lexical_score"),
                combined_confidence_breakdown=c.get("combined_confidence_breakdown"),
                sources_used=c.get("sources_used"),
                lexical_confidence=c.get("lexical_confidence"),
                lexical_matches=c.get("lexical_matches"),
                lexical_total_terms=c.get("lexical_total_terms"),
                wikidata_value=c.get("wikidata_value"),
                wikidata_url=c.get("wikidata_url"),
                wikidata_property_id=c.get("wikidata_property_id"),
                wikidata_property_match=c.get("wikidata_property_match"),
                wikidata_evidence_text=c.get("wikidata_evidence_text"),
                restcountries_url=c.get("restcountries_url"),
                restcountries_evidence_text=c.get("restcountries_evidence_text"),
                verdict_primary=c.get("verdict_primary"),
                verdict_secondary=c.get("verdict_secondary"),
                freshness_checked_at=c.get("freshness_checked_at"),
                freshness_max_age_days=c.get("freshness_max_age_days"),
                resolved_entity=c.get("resolved_entity"),
                resolved_attribute=c.get("resolved_attribute"),
                match_category=c.get("match_category"),
                evidence_location=c.get("evidence_location"),
                evidence_sentence=c.get("evidence_sentence"),
            )
            for c in result.get("results", [])
        ]
        total = result["total"]
        verified_n = result["verified"]
        accuracy = (verified_n / total * 100) if total > 0 else 0.0
        return VerifyResponse(
            question=request.question,
            response=request.response,
            model_used=request.model_used or "llama3",
            total_claims=total,
            verified_claims=verified_n,
            accuracy=round(accuracy, 1),
            verdict=result["verdict"],
            verdict_primary=result.get("verdict_primary"),
            verdict_secondary=result.get("verdict_secondary"),
            verdict_explanation=result.get("verdict_explanation"),
            nyaya_verdict=result.get("nyaya_verdict"),
            hallucination_percent=result.get("hallucination_percent", 0.0) or 0.0,
            hallucination_label=result.get("hallucination_label", "No claims detected"),
            nyaya_explainability=result.get("nyaya_explainability"),
            claims=claims,
        )
    except Exception as e:
        logger.exception("Verification failed")
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/full")
async def full_pipeline(request: GenerateRequest):
    try:
        gen_result = await generate_response(request)
        verify_result = await verify_response(
            VerifyRequest(
                question=gen_result.question,
                response=gen_result.response,
                model_used=gen_result.model_used,
            )
        )
        return {
            "question": gen_result.question,
            "ai_response": gen_result.response,
            "verification": verify_result,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Full pipeline failed")
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/models")
async def list_models():
    fallback: List[dict[str, Any]] = [
        {"id": "llama3", "name": "Llama 3", "description": "Meta Llama 3 (if installed)"},
        {"id": "mistral", "name": "Mistral", "description": "Mistral (if installed)"},
        {"id": "phi3", "name": "Phi-3", "description": "Microsoft Phi (if installed)"},
    ]
    try:
        data = await app.state.ollama.list()
        raw = data.get("models") or []
        out = []
        for m in raw:
            name = m.get("name") or ""
            if not name:
                continue
            out.append(
                {
                    "id": name,
                    "name": name,
                    "size": m.get("size"),
                    "modified_at": m.get("modified_at"),
                }
            )
        return {"models": out, "default": "llama3", "source": "ollama"}
    except Exception as e:
        logger.warning("Ollama list failed, using static fallback: %s", e)
        return {"models": fallback, "default": "llama3", "source": "fallback"}


@app.get("/stats")
async def get_stats():
    return {
        "entity_database_size": len(verifier.known_entities),
        "important_terms": len(verifier.important_terms),
        "internal_sanity_tests": 20,
        "note": "Verifier accuracy must be measured on a held-out benchmark; do not treat internal tests as research metrics.",
        "version": "2.2.0",
        "nyaya_principles": 4,
        "nyaya_verdicts": 4,
        "ollama": {
            "client": "official ollama Python package (HTTP)",
            "read_timeout_max_seconds": settings.OLLAMA_READ_TIMEOUT_MAX,
        },
        "verifier": {
            "hybrid": "Wikipedia text + optional Wikidata snippets + optional sentence-transformer fusion",
            "env": "NYAYA_DISABLE_SEMANTIC, NYAYA_DISABLE_WIKIDATA, NYAYA_SEMANTIC_WEIGHT",
        },
    }


@app.get("/experiments/list")
async def experiments_list():
    """
    List available research JSON outputs from `data/results/`.
    Read-only; safe path handling (no path traversal).
    """
    base = _results_dir().resolve()
    base.mkdir(parents=True, exist_ok=True)

    files: List[dict[str, Any]] = []
    for p in base.glob("*.json"):
        parsed: Any = {}
        try:
            parsed = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            parsed = {}

        files.append(
            {
                "name": p.name,
                "category": _infer_category(p.name),
                "generated_at": parsed.get("generated_at"),
                "size_bytes": p.stat().st_size,
                "mtime": p.stat().st_mtime,
            }
        )

    # Newest first.
    files.sort(key=lambda x: x.get("generated_at") or "", reverse=True)
    files.sort(key=lambda x: x.get("mtime") or 0, reverse=True)
    for f in files:
        f.pop("mtime", None)
    return {"files": files}


@app.get("/experiments/file")
async def experiments_file(name: str):
    """Return one JSON output from `data/results/`."""
    payload = _safe_read_results_json(name)
    return {"name": name, "category": _infer_category(name), "data": payload}


@app.post("/stream")
async def stream_response(request: GenerateRequest):
    return {
        "message": "Streaming not yet implemented. Use /generate or Ollama streaming API directly.",
        "suggestion": "For long answers, increase NYAYA_OLLAMA_READ_MAX or use a smaller model.",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.api:app", host="0.0.0.0", port=8000, reload=False)
