"""
Guardrails for non-LLM / error-like responses.
These strings should not enter claim extraction or hallucination scoring.
"""
from __future__ import annotations

import re

_ERROR_PATTERNS = [
    r"^\s*error\s*:",
    r"^\s*traceback\b",
    r"\bexception\b",
    r"\bmodule\s+not\s+found\b",
    r"\bconnection\s+refused\b",
    r"\bfailed\s+to\s+(generate|verify|fetch|connect)\b",
    r"\bhttp\s*(status|error)\b",
    r"\btimeout\b",
]


def looks_like_system_error_response(text: str) -> bool:
    s = (text or "").strip()
    if not s:
        return True
    sl = s.lower()
    if sl.startswith("<!doctype html") or sl.startswith("<html"):
        return True
    for pat in _ERROR_PATTERNS:
        if re.search(pat, s, re.I):
            return True
    return False

