"""
Canonical ASGI entrypoint for Uvicorn.

Run from the project root (folder that contains `backend/`):

  uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

Or:

  python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
"""
from backend.api import app

__all__ = ["app"]
