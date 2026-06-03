"""
Ollama access via the official Python client (HTTP), not subprocess.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Optional

import httpx
from ollama import AsyncClient, Client
from ollama import RequestError, ResponseError

from backend.core import settings

logger = logging.getLogger(__name__)

_MODEL_RE = re.compile(r"^[a-zA-Z0-9_:.+\-]+$")

_COMPLEX_HINTS = (
    "covid",
    "pandemic",
    "world war",
    "history of",
    "explain",
    "describe",
    "tell me about",
)

_SYSTEM_CUTOFF_PROMPT = (
    "Your knowledge cutoff is 2023. For current events after 2023, your response may be outdated. "
    "Answer clearly, and avoid claiming certainty for post-2023 facts."
)


def validate_model_name(model: str) -> str:
    name = model.strip()
    if not name or len(name) > settings.MAX_MODEL_NAME_LEN:
        raise ValueError("Invalid model name length")
    if not _MODEL_RE.match(name):
        raise ValueError("Model name contains invalid characters")
    return name


def is_complex_prompt(prompt: str) -> bool:
    lower = prompt.lower()
    return any(h in lower for h in _COMPLEX_HINTS)


def read_timeout_for_prompt(prompt: str) -> float:
    return (
        settings.OLLAMA_READ_COMPLEX
        if is_complex_prompt(prompt)
        else settings.OLLAMA_READ_SIMPLE
    )


def _client_kwargs(read_timeout: float) -> dict:
    timeout = httpx.Timeout(
        connect=settings.OLLAMA_CONNECT_TIMEOUT,
        read=read_timeout,
        write=120.0,
        pool=20.0,
    )
    return {"timeout": timeout}


def chat_sync(model: str, prompt: str, read_timeout: Optional[float] = None) -> str:
    """Single-shot sync chat; opens a short-lived HTTP client."""
    read_timeout = read_timeout or read_timeout_for_prompt(prompt)
    model = validate_model_name(model)
    client = Client(**_client_kwargs(read_timeout))
    try:
        resp = client.chat(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM_CUTOFF_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
        text = (resp.get("message") or {}).get("content") or ""
        return text.strip()
    except ResponseError as e:
        logger.warning("Ollama ResponseError: %s", e)
        return f"Error: Ollama could not complete the request ({e}). Is the model pulled? Try: ollama pull {model}"
    except RequestError as e:
        logger.warning("Ollama RequestError: %s", e)
        return f"Error: Invalid request to Ollama ({e})."
    except httpx.TimeoutException:
        logger.warning("Ollama read timeout model=%s", model)
        return (
            "Error: The model took too long to respond. Try a shorter or more specific question, "
            "or increase NYAYA_OLLAMA_READ_SIMPLE / NYAYA_OLLAMA_READ_COMPLEX."
        )
    except httpx.RequestError as e:
        logger.exception("Ollama HTTP error")
        return f"Error: Cannot reach Ollama at {os.getenv('OLLAMA_HOST', 'http://127.0.0.1:11434')}: {e}"


async def chat_async(client: AsyncClient, model: str, prompt: str) -> str:
    """Chat using a shared AsyncClient (long read timeout configured on the client)."""
    model = validate_model_name(model)
    try:
        resp = await client.chat(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM_CUTOFF_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
        text = (resp.get("message") or {}).get("content") or ""
        return text.strip()
    except ResponseError as e:
        logger.warning("Ollama ResponseError: %s", e)
        return f"Error: Ollama could not complete the request ({e}). Is the model pulled? Try: ollama pull {model}"
    except RequestError as e:
        logger.warning("Ollama RequestError: %s", e)
        return f"Error: Invalid request to Ollama ({e})."
    except httpx.TimeoutException:
        logger.warning("Ollama read timeout model=%s", model)
        return (
            "Error: The model took too long to respond. Try a shorter or more specific question, "
            "or increase NYAYA_OLLAMA_READ_MAX."
        )
    except httpx.RequestError as e:
        logger.exception("Ollama HTTP error")
        return f"Error: Cannot reach Ollama: {e}"


class LLMInterface:
    """Backward-compatible wrapper used by tests and the /query route."""

    def __init__(self, model_name: str = "llama3"):
        self.model_name = validate_model_name(model_name)

    def generate_response(self, prompt: str) -> str:
        return chat_sync(self.model_name, prompt)
