"""
Quick offline checks (no Ollama required).

From the project root (the folder that contains `backend/` and `scripts/`):

  python scripts/smoke_imports.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    from backend.main import app

    assert app.title == "NyayaNLP API"

    from backend.models.llm_interface import LLMInterface, validate_model_name

    validate_model_name("llama3")
    validate_model_name("llama3:latest")
    try:
        validate_model_name("bad name!")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for invalid model name")

    LLMInterface("llama3")
    print("OK: imports, validators, and app load succeeded.")
    print("Next: start Ollama, then run:")
    print(f"  cd {ROOT}")
    print("  python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000")
    print("  curl http://127.0.0.1:8000/health")


if __name__ == "__main__":
    main()
