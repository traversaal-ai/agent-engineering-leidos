"""Vercel entrypoint.

Vercel bundles this file as a serverless function and serves the FastAPI app
from it. The real application lives in ../backend; this only fixes up the
import path and the document locations, which are relative paths locally.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

# Locally these default to paths relative to backend/. In the bundle everything
# sits under the project root, so point at it explicitly.
os.environ.setdefault(
    "RAG_DOCUMENT_PATH",
    os.path.join(ROOT, "Project-Management-2nd-Edition-1729807212.pdf"),
)
os.environ.setdefault("RAG_DATA_DIR", os.path.join(ROOT, "data"))

from main import app  # noqa: E402

__all__ = ["app"]
