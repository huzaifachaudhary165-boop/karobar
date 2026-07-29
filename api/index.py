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
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

# An exception raised while importing the app aborts the whole function, and the
# platform reports only FUNCTION_INVOCATION_FAILED — no exception type, no
# message, nothing that says which setting or missing package caused it. Three
# separate boot failures on this deployment were each diagnosed by guesswork
# because of that. Catching it here turns an opaque platform error into an
# answer, at the cost of the process staying up long enough to give one.
_app = None
_boot_error: str | None = None

try:
    from app.main import app as _app  # noqa: E402  — path must be set first
except BaseException as exc:  # noqa: BLE001 — a failed boot must still report
    _boot_error = f"{type(exc).__name__}: {exc}"
    traceback.print_exc()  # the full trace goes to the platform's own logs


# vercel.json rewrites every request to `/api/index/<original path>`. Vercel
# hands the *rewritten* path to the function, so FastAPI would see
# `/api/index/health/ready` and answer 404 for every route in the app.
#
# The prefix is carried explicitly in the rewrite and stripped here rather than
# recovered from a header, because that makes the round trip verifiable: the
# same two lines of config and code fully describe it, with nothing depending on
# which headers the platform happens to forward.
_PREFIX = "/api/index"


async def _report_boot_failure(scope, receive, send) -> None:
    """Answer every request with why the app could not start.

    Only the exception type and message — never the traceback, which carries
    file paths, and never the settings themselves, which carry credentials.
    """
    body = (
        b'{"error":{"code":"boot_failed",'
        b'"message":"The server could not start. Check the deployment logs.",'
        b'"details":{"reason":"' + _boot_error.encode("utf8", "replace")
        .replace(b'\\', b'\\\\').replace(b'"', b'\\"')[:400] + b'"}}}'
    )
    await send({
        "type": "http.response.start",
        "status": 500,
        "headers": [(b"content-type", b"application/json")],
    })
    await send({"type": "http.response.body", "body": body})


async def app(scope, receive, send):
    if _app is None:
        if scope["type"] == "http":
            await _report_boot_failure(scope, receive, send)
        return

    if scope["type"] in ("http", "websocket"):
        path = scope.get("path", "")
        if path == _PREFIX or path.startswith(_PREFIX + "/"):
            trimmed = path[len(_PREFIX):] or "/"
            scope = {**scope, "path": trimmed, "raw_path": trimmed.encode()}

    await _app(scope, receive, send)


__all__ = ["app"]
