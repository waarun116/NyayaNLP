"""
Lazy-loaded sentence embeddings for claim–evidence similarity (optional).

Set NYAYA_DISABLE_SEMANTIC=1 to skip loading models (faster imports, lexical-only).
"""
from __future__ import annotations

import logging
import os
import re
from typing import List, Optional

logger = logging.getLogger(__name__)

_model = None
_load_failed = False


def _env_disabled() -> bool:
    return os.environ.get("NYAYA_DISABLE_SEMANTIC", "").lower() in ("1", "true", "yes")


def get_sentence_model():
    """Return a SentenceTransformer or None if disabled / unavailable."""
    global _model, _load_failed
    if _env_disabled() or _load_failed:
        return None
    if _model is not None:
        return _model
    try:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer("all-MiniLM-L6-v2")
        logger.info("Loaded sentence-transformers model all-MiniLM-L6-v2")
    except Exception as e:
        _load_failed = True
        logger.warning("Semantic verification disabled (model load failed): %s", e)
        return None
    return _model


def _chunk_evidence(text: str, min_chars: int, max_chunks: int) -> List[str]:
    text = (text or "").strip()
    if not text:
        return []
    parts = re.split(r"(?<=[.!?])\s+", text)
    out = []
    for p in parts:
        p = p.strip()
        if len(p) >= min_chars:
            out.append(p)
    if not out:
        out = [text[:2000]]
    return out[:max_chunks]


def max_cosine_similarity(claim: str, evidence_text: str, max_chunks: int, min_sentence_chars: int) -> Optional[float]:
    """
    Max cosine similarity between the claim and evidence sentences.
    Returns 0.0–1.0, or None if semantic path is unavailable.
    """
    model = get_sentence_model()
    if model is None:
        return None
    claim = (claim or "").strip()
    evidence_text = (evidence_text or "").strip()
    if not claim or not evidence_text:
        return None
    chunks = _chunk_evidence(evidence_text, min_sentence_chars, max_chunks)
    if not chunks:
        return None
    try:
        from sentence_transformers import util

        emb_c = model.encode(claim, convert_to_tensor=True)
        emb_s = model.encode(chunks, convert_to_tensor=True)
        sims = util.cos_sim(emb_c, emb_s)
        mx = sims.max()
        return float(mx.item() if hasattr(mx, "item") else mx)
    except Exception as e:
        logger.warning("Semantic similarity failed: %s", e)
        return None
