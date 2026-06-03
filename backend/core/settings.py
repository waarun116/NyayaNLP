"""Central limits and timeouts (env-overridable where noted)."""
import os


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


MAX_QUESTION_CHARS = _int("NYAYA_MAX_QUESTION_CHARS", 8000)
MAX_RESPONSE_CHARS = _int("NYAYA_MAX_RESPONSE_CHARS", 100_000)
MAX_MODEL_NAME_LEN = _int("NYAYA_MAX_MODEL_NAME_LEN", 128)

# Ollama HTTP timeouts (seconds)
OLLAMA_CONNECT_TIMEOUT = _float("NYAYA_OLLAMA_CONNECT_TIMEOUT", 20.0)
OLLAMA_READ_SIMPLE = _float("NYAYA_OLLAMA_READ_SIMPLE", 120.0)
OLLAMA_READ_COMPLEX = _float("NYAYA_OLLAMA_READ_COMPLEX", 240.0)
# Upper bound for shared AsyncClient (must be >= complex)
OLLAMA_READ_TIMEOUT_MAX = _float("NYAYA_OLLAMA_READ_MAX", 300.0)

# Semantic cosine similarity floor (0–1): above this, confidence gets a boost to reduce false negatives
# when Wikipedia evidence aligns but lexical matching is weak. Alias: SIMILARITY_THRESHOLD.
SEMANTIC_VERIFY_FLOOR = _float(
    "NYAYA_SEMANTIC_VERIFY_FLOOR",
    _float("SIMILARITY_THRESHOLD", 0.25),
)
