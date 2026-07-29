"""Vercel serverless entry point.

Vercel looks for a module-level ASGI app called `app` inside `api/`. Everything
real lives in `backend/app`; this file puts that package on the path, re-exports
it, and undoes the one thing Vercel's routing does to the request.

Read `docs/DEPLOY.md` before relying on this — a serverless host imposes real
constraints on this app (cold starts, a request timeout the assistant can
exceed, no local disk, and rate limiting that stops working). A container host
is the better fit; this exists because Vercel was asked for.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.main import app as _app  # noqa: E402  — path must be set first

# vercel.json rewrites every request to `/api/index/<original path>`. Vercel
# hands the *rewritten* path to the function, so FastAPI would see
# `/api/index/health/ready` and answer 404 for every route in the app.
#
# The prefix is carried explicitly in the rewrite and stripped here rather than
# recovered from a header, because that makes the round trip verifiable: the
# same two lines of config and code fully describe it, with nothing depending on
# which headers the platform happens to forward.
_PREFIX = "/api/index"


async def app(scope, receive, send):
    if scope["type"] in ("http", "websocket"):
        path = scope.get("path", "")
        if path == _PREFIX or path.startswith(_PREFIX + "/"):
            trimmed = path[len(_PREFIX):] or "/"
            scope = {**scope, "path": trimmed, "raw_path": trimmed.encode()}
    await _app(scope, receive, send)


__all__ = ["app"]
