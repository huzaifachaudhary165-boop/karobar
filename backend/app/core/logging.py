"""Structured logging setup — JSON in production, pretty console in dev."""

from __future__ import annotations

import logging
import sys
from contextvars import ContextVar

import structlog

from app.core.config import settings

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")
user_id_ctx: ContextVar[str] = ContextVar("user_id", default="-")
business_id_ctx: ContextVar[str] = ContextVar("business_id", default="-")


def _inject_context(_logger, _name, event_dict):
    event_dict["request_id"] = request_id_ctx.get()
    uid = user_id_ctx.get()
    if uid != "-":
        event_dict["user_id"] = uid
    bid = business_id_ctx.get()
    if bid != "-":
        event_dict["business_id"] = bid
    return event_dict


def _force_utf8_stdio() -> None:
    """Stop a log line from killing the request that produced it.

    A Windows console defaults to cp1252, so the first Urdu item name or a `—`
    in an exception message raises UnicodeEncodeError *inside the error
    handler* — turning a clean 4xx into an unhandled 500 with the real cause
    buried. Replacing unencodable characters is always better than crashing.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):  # pragma: no cover — detached/odd stream
            pass


# Applied at import, not inside configure_logging(): anything that logs before
# startup runs — a CLI command, a test using ASGITransport, an import-time
# warning — must not be able to die on an encoding error.
_force_utf8_stdio()


def configure_logging() -> None:
    level = logging.DEBUG if settings.DEBUG else logging.INFO

    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)
    # These are chatty at DEBUG and drown out anything useful.
    for noisy in (
        "uvicorn.access", "sqlalchemy.engine.Engine", "httpx", "httpcore",
        "aiosqlite", "asyncio", "httpcore", "PIL", "multipart",
    ):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _inject_context,
        structlog.processors.StackInfoRenderer(),
    ]
    if settings.is_production:
        # ConsoleRenderer formats exceptions itself; format_exc_info would fight it.
        processors += [structlog.processors.format_exc_info, structlog.processors.JSONRenderer()]
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=True))

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = "karobar"):
    return structlog.get_logger(name)


log = get_logger()
