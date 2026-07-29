"""Vercel serverless entry point.

Vercel looks for a module-level ASGI app called `app` inside `api/`. Everything
real lives in `backend/app`; this file only puts that package on the path and
re-exports it.

Read `docs/DEPLOY.md` before relying on this — a serverless host imposes real
constraints on this app (cold starts, a request timeout that the assistant can
exceed, no local disk, and rate limiting that stops working). A container host
is the better fit; this exists because Vercel was asked for.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.main import app  # noqa: E402  — path must be set first

__all__ = ["app"]
