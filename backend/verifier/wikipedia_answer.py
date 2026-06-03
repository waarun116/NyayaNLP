"""
Build a short, question-relevant answer from Wikipedia summary (not raw source dumps).
Used when evidence-based claims fail but we still want a source-aligned reply to the user's question.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

import wikipediaapi

_WIKI = wikipediaapi.Wikipedia(
    language="en",
    user_agent="NyayaVerifier/correct_answer (https://localhost; research)",
)


def _extract_search_topic(question: str) -> Optional[str]:
    q = (question or "").strip()
    if not q:
        return None
    patterns = [
        # "who built/created/designed/painted X"
        (r"(?i)\bwho\s+(?:built|constructed|designed|created|commissioned|founded|wrote|composed|painted)\s+(?:the\s+)?(.+?)\??$", 1),
        # "who invented X"
        (r"(?i)\bwho\s+(?:invented|invents|inventor|developed|discovered|discovered)\s+(?:the\s+)?(.+?)\??$", 1),
        # "what is X"
        (r"(?i)\bwhat\s+is\s+(?:the\s+)?(.+?)\??$", 1),
        (r"(?i)\bwho\s+is\s+(?:the\s+)?(.+?)\??$", 1),
        (r"(?i)\b(?:where\s+is|where\s+was|where\s+are)\s+(?:the\s+)?(.+?)\??$", 1),
        (r"(?i)\bwhen\s+(?:was|did|is)\s+(?:the\s+)?(.+?)\??$", 1),
        (r"(?i)\bwhy\s+(?:was|did|is)\s+(?:the\s+)?(.+?)\??$", 1),
        (r"(?i)\bhow\s+(?:was|did)\s+(?:the\s+)?(.+?)\??$", 1),
    ]
    for pat, gidx in patterns:
        m = re.search(pat, q)
        if m:
            topic = (m.group(gidx) or "").strip()
            topic = topic.strip("\"'“”")
            if len(topic) >= 2:
                return topic[:200]
    return None


def get_factual_snippet_for_question(question: str) -> Tuple[Optional[str], List[Dict[str, str]]]:
    """
    Return (plain-language answer citing Wikipedia lead, citations).
    """
    topic = _extract_search_topic(question)
    if not topic:
        return None, []

    page = _WIKI.page(topic)
    if not page.exists():
        page = _WIKI.page(topic[:1].upper() + topic[1:] if topic else topic)
    if not page.exists():
        # Title case each word for "taj mahal" -> "Taj Mahal"
        titled = " ".join(w.capitalize() for w in topic.split())
        page = _WIKI.page(titled)
    if not page.exists():
        return None, []

    summ = (page.summary or "").strip()
    if not summ:
        return None, []

    parts = re.split(r"(?<=[.!?])\s+", summ)
    lead = " ".join(parts[:3]).strip()
    if len(lead) > 900:
        lead = lead[:897] + "..."

    import urllib.parse

    title = page.title.replace(" ", "_")
    url = "https://en.wikipedia.org/wiki/" + urllib.parse.quote(title)
    cite = [{"label": "Wikipedia", "url": url}]
    answer = (
        f"For your question, a widely accepted summary from Wikipedia is: {lead}"
    )
    return answer, cite
