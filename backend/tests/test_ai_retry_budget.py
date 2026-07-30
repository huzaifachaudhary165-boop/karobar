"""Retrying a throttled assistant call must not outlive the request.

The free Groq tier is measured in tokens per minute, so a shopkeeper who sends
two messages in a row gets a 429. Retrying that is right — but two retries at up
to 20s each is 40s of sleeping on top of three real calls, and the host cuts the
request off at 60s. Measured on the deployment, a throttled turn took 44s and
then 60s and died: the person watched a spinner for a minute and got a generic
failure that did not even mention throttling.

These tests pin the rule that fixes it: wait only while the answer can still be
delivered, and when it cannot, say so immediately and say for how long.
"""

from __future__ import annotations

import time

import httpx
import pytest

from app.ai import client as client_module
from app.ai.client import AiClient
from app.core.errors import AIError


class FakeResponse:
    """Enough of httpx.Response for the retry loop."""

    def __init__(self, status_code: int, headers: dict[str, str] | None = None):
        self.status_code = status_code
        self.headers = httpx.Headers(headers or {})
        self.text = '{"error":{"message":"rate limit reached"}}'

    def json(self) -> dict:
        return {"choices": [{"message": {"content": "ok"}}]}


def patch_transport(monkeypatch, responses: list[FakeResponse]) -> dict:
    """Replies with each response in turn, and records how long was slept."""
    state = {"calls": 0, "slept": 0.0}
    queue = list(responses)

    class FakeClient:
        def __init__(self, **_):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def post(self, *_args, **_kwargs):
            state["calls"] += 1
            return queue.pop(0) if queue else FakeResponse(200)

    async def fake_sleep(seconds):
        # Sleep is recorded, never actually waited — the test must stay fast and
        # must measure the *decision*, not the clock.
        state["slept"] += seconds

    monkeypatch.setattr(client_module.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(client_module.asyncio, "sleep", fake_sleep)
    return state


def a_client(monkeypatch, budget: float) -> AiClient:
    monkeypatch.setattr(client_module.settings, "GROQ_API_KEY", "test-key")
    monkeypatch.setattr(client_module.settings, "AI_REQUEST_BUDGET_SECONDS", budget)
    return AiClient()


@pytest.mark.asyncio
async def test_a_throttled_call_is_retried_when_there_is_time(monkeypatch):
    state = patch_transport(monkeypatch, [
        FakeResponse(429, {"retry-after": "3"}),
        FakeResponse(200),
    ])
    ai = a_client(monkeypatch, budget=40.0)

    result = await ai._post("/chat/completions", {})

    assert result, "the retry should have produced an answer"
    assert state["calls"] == 2
    assert state["slept"] == pytest.approx(3.0)


@pytest.mark.asyncio
async def test_a_wait_that_would_outlive_the_request_is_refused(monkeypatch):
    """The whole point. A 20s wait inside a 10s budget cannot deliver a reply,
    so waiting it out only converts a fast honest error into a slow useless one."""
    state = patch_transport(monkeypatch, [FakeResponse(429, {"retry-after": "20"})])
    ai = a_client(monkeypatch, budget=10.0)

    with pytest.raises(AIError) as exc:
        await ai._post("/chat/completions", {})

    assert exc.value.code == "ai_rate_limited"
    assert state["slept"] == 0.0, "it must not have waited at all"
    assert state["calls"] == 1


@pytest.mark.asyncio
async def test_the_refusal_says_how_long_to_wait(monkeypatch):
    """"Try again in a moment" is not something a person can act on."""
    patch_transport(monkeypatch, [FakeResponse(429, {"retry-after": "17"})])
    ai = a_client(monkeypatch, budget=10.0)

    with pytest.raises(AIError) as exc:
        await ai._post("/chat/completions", {})

    assert "17 seconds" in str(exc.value)
    assert "per-minute limit" in str(exc.value)


@pytest.mark.asyncio
async def test_the_total_wait_stays_inside_the_budget(monkeypatch):
    """Repeated throttling must not add up past the ceiling either."""
    state = patch_transport(monkeypatch, [
        FakeResponse(429, {"retry-after": "10"}),
        FakeResponse(429, {"retry-after": "10"}),
        FakeResponse(429, {"retry-after": "10"}),
    ])
    ai = a_client(monkeypatch, budget=25.0)

    with pytest.raises(AIError):
        await ai._post("/chat/completions", {})

    assert state["slept"] <= 25.0, f"slept {state['slept']}s inside a 25s budget"


@pytest.mark.asyncio
async def test_an_error_that_is_not_worth_retrying_is_raised_at_once(monkeypatch):
    state = patch_transport(monkeypatch, [FakeResponse(401)])
    ai = a_client(monkeypatch, budget=40.0)

    with pytest.raises(AIError) as exc:
        await ai._post("/chat/completions", {})

    assert exc.value.code == "ai_auth_failed"
    assert state["calls"] == 1
    assert state["slept"] == 0.0


@pytest.mark.asyncio
async def test_a_successful_call_never_sleeps(monkeypatch):
    state = patch_transport(monkeypatch, [FakeResponse(200)])
    ai = a_client(monkeypatch, budget=40.0)

    await ai._post("/chat/completions", {})

    assert state["calls"] == 1
    assert state["slept"] == 0.0


@pytest.mark.asyncio
async def test_the_budget_is_measured_from_the_start_of_the_turn(monkeypatch):
    """Time already spent counts against the wait, not just the wait itself."""
    state = patch_transport(monkeypatch, [
        FakeResponse(429, {"retry-after": "5"}),
        FakeResponse(429, {"retry-after": "5"}),
    ])

    # Each call appears to take 12s of wall clock.
    clock = {"t": 0.0}
    monkeypatch.setattr(client_module.time, "monotonic", lambda: clock["t"])

    original = client_module.httpx.AsyncClient

    class SlowClient(original):  # type: ignore[misc, valid-type]
        async def post(self, *args, **kwargs):
            clock["t"] += 12.0
            return await super().post(*args, **kwargs)

    monkeypatch.setattr(client_module.httpx, "AsyncClient", SlowClient)
    ai = a_client(monkeypatch, budget=25.0)

    with pytest.raises(AIError):
        await ai._post("/chat/completions", {})

    # 12s spent + 5s wait + the allowance for the retried call exceeds 25s, so
    # the second wait must be refused.
    assert state["slept"] <= 5.0


def test_the_budget_leaves_room_under_the_hosts_ceiling():
    """Vercel cuts a request off at 60s. A budget at or above that cannot help."""
    from app.core.config import Settings

    budget = Settings(_env_file="").AI_REQUEST_BUDGET_SECONDS
    assert budget + client_module._MIN_CALL_ALLOWANCE <= 60, (
        f"a {budget}s budget plus the call allowance can still be cut off"
    )
    assert budget > 20, "too small to allow any real retry"


def test_retry_after_is_capped_but_respected():
    headers = httpx.Headers({"retry-after": "3"})
    assert client_module._retry_after(headers, 0) == 3.0

    # A server asking for longer than we are willing to wait is clamped.
    huge = httpx.Headers({"retry-after": "600"})
    assert client_module._retry_after(huge, 0) == client_module._MAX_RETRY_WAIT

    # No header: exponential backoff, still clamped.
    assert client_module._retry_after(httpx.Headers({}), 0) == 2.0
    assert client_module._retry_after(httpx.Headers({}), 9) == client_module._MAX_RETRY_WAIT


def test_wall_clock_is_not_consulted_for_the_decision():
    """A guard against reintroducing time.sleep: the tests above fake the clock,
    so a real sleep would make the suite slow rather than fail."""
    started = time.monotonic()
    client_module._retry_after(httpx.Headers({"retry-after": "20"}), 0)
    assert time.monotonic() - started < 1.0
