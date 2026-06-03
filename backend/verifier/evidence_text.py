"""Build plaintext evidence strings from Wikipedia pages."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def wikipedia_evidence_raw(page, text_max_chars: int) -> str:
    """
    Summary plus a capped full extract when available.
    """
    parts = [page.summary or "", page.title or ""]
    if text_max_chars > 0:
        try:
            body = page.text
            if body:
                parts.append(body[:text_max_chars])
        except Exception as e:
            logger.debug("Could not load full page text: %s", e)
    return "\n".join(p for p in parts if p)
