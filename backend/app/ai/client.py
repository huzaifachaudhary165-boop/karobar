"""Groq client wrapper: retries, rate-limit handling, usage accounting.

Everything the app sends to the model goes through here so token spend, latency
and throttling are measured in one place.

Groq speaks the OpenAI chat-completions shape. The rest of the app speaks a
content-block shape (`text` / `tool_use` / `tool_result`) which is what
`AiMessage.blocks` stores in the database. Translating between the two lives
here and nowhere else — the agent, OCR and insights layers never see wire
format. That also means the stored transcript of a conversation stays readable
if the provider is ever swapped again.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

import httpx

from app.core.config import settings
from app.core.errors import AIError
from app.core.logging import log

# Groq sits behind Cloudflare, which rejects requests with no User-Agent.
_HEADERS_BASE = {"User-Agent": "karobar/1.0", "Content-Type": "application/json"}

# The free tier is measured in tokens-per-minute, so a burst gets throttled long
# before the daily request cap matters. One patient retry turns most 429s into a
# slightly slower reply instead of an error the shopkeeper has to read.
_MAX_RETRIES = 2
_MAX_RETRY_WAIT = 20.0


@dataclass(slots=True)
class AiResult:
    """Normalised view of one model response, in the app's own block shape."""

    content: list[dict[str, Any]] = field(default_factory=list)
    text: str = ""
    stop_reason: str | None = None
    model: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    latency_ms: int = 0
    refusal_category: str | None = None

    @property
    def is_refusal(self) -> bool:
        return self.stop_reason == "refusal"

    @property
    def tool_uses(self) -> list[dict[str, Any]]:
        return [b for b in self.content if b.get("type") == "tool_use"]

    @property
    def estimated_cost_usd(self) -> float:
        return (
            self.input_tokens / 1_000_000 * settings.AI_INPUT_COST_PER_MTOK
            + self.output_tokens / 1_000_000 * settings.AI_OUTPUT_COST_PER_MTOK
        )


class AiClient:
    """Thin async wrapper over Groq's OpenAI-compatible chat completions API."""

    def __init__(self, api_key: str | None = None, base_url: str | None = None) -> None:
        self.api_key = api_key or settings.GROQ_API_KEY
        self.base_url = (base_url or settings.GROQ_BASE_URL).rstrip("/")

    @property
    def available(self) -> bool:
        return bool(self.api_key) and settings.AI_ENABLED

    def _assert_available(self) -> None:
        if not self.available:
            raise AIError(
                "The AI assistant is not configured. Add GROQ_API_KEY to your .env file.",
                code="ai_not_configured",
            )

    @property
    def _headers(self) -> dict[str, str]:
        return {**_HEADERS_BASE, "Authorization": f"Bearer {self.api_key}"}

    # ── core call ────────────────────────────────────────────────
    async def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        system: str | list[dict[str, Any]] | None = None,
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        effort: str | None = None,
        output_schema: dict[str, Any] | None = None,
        tool_choice: dict[str, Any] | None = None,
    ) -> AiResult:
        """One non-streaming request.

        `effort` is accepted for call-site compatibility and mapped onto Groq's
        `reasoning_effort`, which only some models honour; the rest ignore it.
        """
        self._assert_available()

        payload: dict[str, Any] = {
            "model": model or settings.AI_MODEL,
            "max_completion_tokens": max_tokens or settings.AI_MAX_TOKENS,
            "messages": to_openai_messages(messages, system=system),
        }
        if tools:
            payload["tools"] = to_openai_tools(tools)
            payload["tool_choice"] = tool_choice or "auto"
        if output_schema:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "result",
                    "schema": strictify(output_schema),
                    "strict": True,
                },
            }
        if reasoning := _reasoning_effort(effort):
            payload["reasoning_effort"] = reasoning

        started = time.perf_counter()
        data = await self._post("/chat/completions", payload)
        elapsed = int((time.perf_counter() - started) * 1000)
        return _normalise(data, elapsed)

    async def stream_text(
        self,
        messages: list[dict[str, Any]],
        *,
        system: str | list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        effort: str | None = None,
    ) -> AsyncIterator[str]:
        """Yield text deltas. Used by the chat endpoint's SSE mode."""
        self._assert_available()

        payload: dict[str, Any] = {
            "model": model or settings.AI_MODEL,
            "max_completion_tokens": max_tokens or settings.AI_MAX_TOKENS,
            "messages": to_openai_messages(messages, system=system),
            "stream": True,
        }
        if reasoning := _reasoning_effort(effort):
            payload["reasoning_effort"] = reasoning

        try:
            async with httpx.AsyncClient(base_url=self.base_url, timeout=120.0) as client:
                async with client.stream(
                    "POST", "/chat/completions", headers=self._headers, json=payload
                ) as response:
                    if response.status_code >= 400:
                        body = (await response.aread()).decode("utf8", "replace")
                        raise self._translate_status(response.status_code, body)

                    async for line in response.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        chunk = line[6:].strip()
                        if chunk == "[DONE]":
                            break
                        try:
                            delta = json.loads(chunk)["choices"][0]["delta"]
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue
                        if piece := delta.get("content"):
                            yield piece
        except httpx.HTTPError as exc:
            raise AIError(
                "Could not reach the assistant. Check your internet connection.",
                code="ai_unreachable",
            ) from exc

    async def vision(
        self,
        *,
        images: list[tuple[str, bytes]],
        prompt: str,
        system: str | None = None,
        output_schema: dict[str, Any] | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        effort: str = "high",
    ) -> AiResult:
        """Not supported on Groq — no model on this plan accepts image input.

        Bills are read on the phone instead: Google ML Kit extracts the text
        on-device (free, offline) and only that text is sent up for structuring.
        See `OcrService.scan_text`.
        """
        raise AIError(
            "Image understanding is not available on this AI plan. "
            "Scan the bill from the app, which reads the text on your phone.",
            code="ai_vision_unsupported",
        )

    async def transcribe(
        self,
        audio: bytes,
        *,
        filename: str = "speech.m4a",
        language: str | None = None,
        prompt: str | None = None,
    ) -> str:
        """Speech to text through Whisper.

        The phone's own recogniser is free and offline, and it is what the app
        uses by default. It is also trained on English and struggles with the
        shop vocabulary people actually speak — "bori", "maal", "udhaar",
        prices said as "bara sau" rather than "one thousand two hundred".
        Whisper handles that far better, so it is offered as the accurate
        option when there is signal.

        `prompt` is not an instruction — Whisper treats it as a hint about the
        vocabulary to expect, which is exactly how the shop's own words are fed
        in.
        """
        self._assert_available()

        form = {
            "model": (None, settings.AI_SPEECH_MODEL),
            "file": (filename, audio, "application/octet-stream"),
            "response_format": (None, "text"),
        }
        if language:
            form["language"] = (None, language)
        if prompt:
            form["prompt"] = (None, prompt[:800])

        try:
            async with httpx.AsyncClient(base_url=self.base_url, timeout=120.0) as client:
                # Multipart, so Content-Type must be left for httpx to set with
                # its own boundary.
                headers = {
                    k: v for k, v in self._headers.items() if k.lower() != "content-type"
                }
                response = await client.post(
                    "/audio/transcriptions", headers=headers, files=form
                )
        except httpx.HTTPError as exc:
            raise AIError(
                "Could not reach the transcription service.", code="ai_unreachable"
            ) from exc

        if response.status_code >= 400:
            raise self._translate_status(response.status_code, response.text)
        return response.text.strip()

    # ── transport ────────────────────────────────────────────────
    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        last_error: AIError | None = None

        for attempt in range(_MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(base_url=self.base_url, timeout=120.0) as client:
                    response = await client.post(path, headers=self._headers, json=payload)
            except httpx.HTTPError as exc:
                raise AIError(
                    "Could not reach the assistant. Check your internet connection.",
                    code="ai_unreachable",
                ) from exc

            if response.status_code < 400:
                _log_budget(response.headers)
                return response.json()

            error = self._translate_status(response.status_code, response.text)

            # Only throttling and upstream blips are worth another go.
            if error.code not in ("ai_rate_limited", "ai_upstream_error"):
                raise error
            if attempt == _MAX_RETRIES:
                raise error

            wait = _retry_after(response.headers, attempt)
            log.warning(
                "ai.retrying",
                status=response.status_code,
                attempt=attempt + 1,
                wait_seconds=round(wait, 1),
            )
            await asyncio.sleep(wait)
            last_error = error

        raise last_error or AIError("The assistant is unavailable.", code="ai_error")

    def _translate_status(self, status: int, body: str) -> AIError:
        detail = body[:500]
        try:
            detail = json.loads(body)["error"]["message"][:500]
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

        if status == 429:
            return AIError(
                "The assistant is busy right now. Please try again in a moment.",
                code="ai_rate_limited",
            )
        if status in (401, 403):
            log.error("ai.auth_failed", status=status, detail=detail)
            return AIError("The AI API key is invalid or blocked.", code="ai_auth_failed")
        if status == 400:
            log.error("ai.bad_request", detail=detail)
            # A 400 is our bug, not the user's — a malformed message list, a tool
            # schema the model rejected, a context that got too long. "Could not
            # process that request" sends the shopkeeper off rewording a
            # perfectly good sentence, and tells whoever reads the bug report
            # nothing. Outside production the upstream reason is included.
            return AIError(
                "The assistant hit a problem on our side, not with what you asked. "
                "Please try again."
                + ("" if settings.is_production else f"\n\n[dev] {detail}"),
                code="ai_bad_request",
                details={"upstream": detail} if not settings.is_production else {},
            )
        if status >= 500:
            log.error("ai.upstream_error", status=status, detail=detail)
            return AIError("The assistant is temporarily unavailable.", code="ai_upstream_error")

        log.error("ai.unexpected_status", status=status, detail=detail)
        return AIError("Something went wrong with the assistant.", code="ai_error")


def strictify(schema: dict[str, Any]) -> dict[str, Any]:
    """Rewrite a JSON schema to satisfy strict structured-output validation.

    Strict mode has one rule that trips up ordinary schemas: every key in
    `properties` must also appear in `required`, at every level, and
    `additionalProperties` must be false. Optionality is expressed by the type
    instead — `{"type": ["string", "null"]}` — which our schemas already do.

    Doing this here rather than in each schema means a new extraction schema
    cannot silently fail validation on its first real call.
    """
    if not isinstance(schema, dict):
        return schema

    out = {k: v for k, v in schema.items() if k != "properties"}

    if isinstance(properties := schema.get("properties"), dict):
        out["properties"] = {key: strictify(value) for key, value in properties.items()}
        out["required"] = list(properties)
        out["additionalProperties"] = False

    if isinstance(items := schema.get("items"), dict):
        out["items"] = strictify(items)

    for keyword in ("anyOf", "oneOf", "allOf"):
        if isinstance(branch := schema.get(keyword), list):
            out[keyword] = [strictify(entry) for entry in branch]

    return out


# ── translation: our blocks ⇄ OpenAI wire format ─────────────────
def to_openai_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """`{name, description, input_schema}` → OpenAI's function-tool envelope."""
    return [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("input_schema") or {"type": "object", "properties": {}},
            },
        }
        for tool in tools
    ]


def to_openai_messages(
    messages: list[dict[str, Any]], *, system: str | list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """Flatten the app's block format into OpenAI chat messages.

    The shapes differ in one structural way: we carry every result of a parallel
    tool batch inside a single user message, while OpenAI wants one `tool`
    message per call. So one of ours can expand into several of theirs.
    """
    out: list[dict[str, Any]] = []

    if system:
        text = system if isinstance(system, str) else _join_text_blocks(system)
        if text:
            out.append({"role": "system", "content": text})

    for message in messages:
        role = message.get("role")
        content = message.get("content")

        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue
        if not isinstance(content, list):
            continue

        if role == "assistant":
            out.append(_assistant_message(content))
            continue

        # A user turn is either plain input or a batch of tool results.
        tool_results = [b for b in content if b.get("type") == "tool_result"]
        if tool_results:
            for block in tool_results:
                out.append(
                    {
                        "role": "tool",
                        "tool_call_id": block.get("tool_use_id", ""),
                        "content": _stringify(block.get("content")),
                    }
                )
            continue

        if text := _join_text_blocks(content):
            out.append({"role": "user", "content": text})

    return out


def _assistant_message(blocks: list[dict[str, Any]]) -> dict[str, Any]:
    tool_calls = [
        {
            "id": block.get("id", ""),
            "type": "function",
            "function": {
                "name": block.get("name", ""),
                "arguments": json.dumps(block.get("input") or {}, ensure_ascii=False),
            },
        }
        for block in blocks
        if block.get("type") == "tool_use"
    ]

    message: dict[str, Any] = {"role": "assistant", "content": _join_text_blocks(blocks)}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return message


def _join_text_blocks(blocks: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for block in blocks:
        kind = block.get("type")
        if kind == "text" and block.get("text"):
            parts.append(block["text"])
        elif kind == "image":
            # No vision on this plan; keep the turn coherent rather than dropping it.
            parts.append("[an image was attached, but it could not be read]")
    return "\n".join(parts).strip()


def _stringify(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


def _normalise(data: dict[str, Any], latency_ms: int) -> AiResult:
    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    finish = choice.get("finish_reason")

    blocks: list[dict[str, Any]] = []
    text = (message.get("content") or "").strip()
    if text:
        blocks.append({"type": "text", "text": text})

    for call in message.get("tool_calls") or []:
        function = call.get("function") or {}
        blocks.append(
            {
                "type": "tool_use",
                "id": call.get("id", ""),
                "name": function.get("name", ""),
                "input": _parse_arguments(function.get("arguments")),
            }
        )

    usage = data.get("usage") or {}
    result = AiResult(
        content=blocks,
        text=text,
        stop_reason=_STOP_REASONS.get(finish, finish),
        model=data.get("model"),
        input_tokens=int(usage.get("prompt_tokens") or 0),
        output_tokens=int(usage.get("completion_tokens") or 0),
        latency_ms=latency_ms,
    )

    if result.stop_reason == "max_tokens":
        log.warning("ai.truncated", output_tokens=result.output_tokens)
    return result


def _parse_arguments(raw: Any) -> dict[str, Any]:
    """Tool arguments arrive as a JSON string. A malformed one becomes `{}` so
    the executor reports a clean validation error instead of the loop crashing."""
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("ai.bad_tool_arguments", raw=str(raw)[:300])
        return {}
    return parsed if isinstance(parsed, dict) else {}


_STOP_REASONS = {
    "stop": "end_turn",
    "tool_calls": "tool_use",
    "function_call": "tool_use",
    "length": "max_tokens",
    "content_filter": "refusal",
}

_EFFORTS = {"low": "low", "medium": "medium", "high": "high", "xhigh": "high", "max": "high"}


def _reasoning_effort(effort: str | None) -> str | None:
    return _EFFORTS.get((effort or settings.AI_EFFORT or "").lower())


def _retry_after(headers: httpx.Headers, attempt: int) -> float:
    """Prefer the server's own advice; fall back to exponential backoff."""
    raw = headers.get("retry-after")
    if raw:
        try:
            return min(float(raw), _MAX_RETRY_WAIT)
        except ValueError:
            pass
    return min(2.0 * (2**attempt), _MAX_RETRY_WAIT)


def _log_budget(headers: httpx.Headers) -> None:
    """Surface how close the free tier's per-minute budget is to running out."""
    remaining = headers.get("x-ratelimit-remaining-tokens")
    if remaining is None:
        return
    try:
        left = int(remaining)
    except ValueError:
        return
    if left < 2000:
        log.warning(
            "ai.budget_low",
            remaining_tokens=left,
            resets_in=headers.get("x-ratelimit-reset-tokens"),
        )


ai_client = AiClient()
