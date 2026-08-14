"""Letting a browser talk to this API.

Karobar runs in a browser as well as on a phone, and a browser will not send a
request the API has not agreed to answer. The failure is quiet: the API returns
200 to anything that asks directly, so it looks healthy from a terminal while
every screen in the web app sits empty.

That is exactly what happened. `allow_origins=["*"]` together with
`allow_credentials=True` is forbidden by the CORS spec, and Starlette obeys it
by sending no allow-origin header at all — a config that reads as permissive
and behaves as closed.
"""

from __future__ import annotations

import httpx
import pytest

from app.main import create_app

ORIGIN = "https://karobar.vercel.app"


def _client(origins: list[str]) -> httpx.AsyncClient:
    from app.core.config import settings

    original = settings.CORS_ORIGINS
    settings.CORS_ORIGINS = origins
    try:
        app = create_app()
    finally:
        settings.CORS_ORIGINS = original

    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    )


@pytest.mark.asyncio
async def test_a_wildcard_actually_lets_a_browser_in():
    """The bug this file exists for.

    Without the allow-origin header the browser throws the response away, so
    the shopkeeper sees an app that loads and then does nothing at all.
    """
    async with _client(["*"]) as client:
        response = await client.get("/health", headers={"Origin": ORIGIN})

    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "*"


@pytest.mark.asyncio
async def test_the_preflight_is_answered():
    """Every POST from a browser is preceded by one of these. A 400 here means
    no bill, no payment and no login ever leaves the page."""
    async with _client(["*"]) as client:
        response = await client.request(
            "OPTIONS",
            "/api/v1/auth/login",
            headers={
                "Origin": ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type,authorization",
            },
        )

    assert response.status_code == 200, response.text
    assert response.headers.get("access-control-allow-origin") == "*"
    assert "POST" in response.headers.get("access-control-allow-methods", "")


@pytest.mark.asyncio
async def test_a_named_origin_is_allowed_and_keeps_credentials():
    """Naming the origins is what a shop in production should be running. It is
    the only form where credentials are legal, so they stay on."""
    async with _client([ORIGIN]) as client:
        response = await client.get("/health", headers={"Origin": ORIGIN})

    assert response.headers.get("access-control-allow-origin") == ORIGIN
    assert response.headers.get("access-control-allow-credentials") == "true"


@pytest.mark.asyncio
async def test_an_origin_that_was_not_named_is_refused():
    async with _client([ORIGIN]) as client:
        response = await client.get(
            "/health", headers={"Origin": "https://somebody-else.example"}
        )

    assert response.headers.get("access-control-allow-origin") is None


@pytest.mark.asyncio
async def test_the_headers_the_app_reads_back_are_exposed():
    """A browser hides every response header unless it is named here, and the
    app reads the request id off failures to report them."""
    async with _client(["*"]) as client:
        response = await client.get("/health", headers={"Origin": ORIGIN})

    exposed = response.headers.get("access-control-expose-headers", "")
    assert "X-Request-Id" in exposed
