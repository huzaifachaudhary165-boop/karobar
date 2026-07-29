"""Translation between the app's content blocks and Groq's OpenAI wire format.

These are the seams where a chat turn gets silently corrupted — a dropped
tool_call_id or a re-ordered tool result produces a model reply that looks
plausible and is wrong. They run offline, with no API key.
"""

from __future__ import annotations

import json

from app.ai.client import (
    _normalise, _parse_arguments, strictify, to_openai_messages, to_openai_tools,
)


# ── tools ────────────────────────────────────────────────────────
def test_tool_definitions_become_openai_functions():
    tools = to_openai_tools(
        [
            {
                "name": "create_invoice",
                "description": "Create a sale invoice",
                "input_schema": {"type": "object", "properties": {"qty": {"type": "number"}}},
            }
        ]
    )
    assert tools[0]["type"] == "function"
    assert tools[0]["function"]["name"] == "create_invoice"
    assert tools[0]["function"]["parameters"]["properties"]["qty"]["type"] == "number"


def test_a_tool_without_a_schema_still_produces_a_valid_object():
    """An argument-less tool must not send `parameters: null`, which is rejected."""
    tools = to_openai_tools([{"name": "get_business_summary", "description": "d"}])
    assert tools[0]["function"]["parameters"] == {"type": "object", "properties": {}}


# ── strict structured output ─────────────────────────────────────
def test_strictify_requires_every_property_at_every_level():
    """Groq rejects a strict schema unless `required` lists all keys — including
    inside array items, which is exactly where the OCR schema nests them."""
    schema = {
        "type": "object",
        "properties": {
            "vendor": {"type": ["string", "null"]},
            "lines": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}, "qty": {"type": ["number", "null"]}},
                    "required": ["name"],
                },
            },
        },
        "required": ["lines"],
    }

    strict = strictify(schema)

    assert set(strict["required"]) == {"vendor", "lines"}
    assert strict["additionalProperties"] is False
    items = strict["properties"]["lines"]["items"]
    assert set(items["required"]) == {"name", "qty"}
    assert items["additionalProperties"] is False


def test_strictify_leaves_the_original_schema_untouched():
    schema = {"type": "object", "properties": {"a": {"type": "string"}}, "required": []}
    strictify(schema)
    assert schema["required"] == []


def test_strictify_ignores_schemas_with_no_properties():
    assert strictify({"type": "string"}) == {"type": "string"}


# ── messages: our blocks → OpenAI ────────────────────────────────
def test_system_blocks_are_joined_into_one_system_message():
    out = to_openai_messages(
        [{"role": "user", "content": [{"type": "text", "text": "hi"}]}],
        system=[{"type": "text", "text": "rules"}, {"type": "text", "text": "context"}],
    )
    assert out[0] == {"role": "system", "content": "rules\ncontext"}
    assert out[1] == {"role": "user", "content": "hi"}


def test_assistant_tool_calls_carry_their_ids_and_json_arguments():
    out = to_openai_messages(
        [
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "banata hoon"},
                    {
                        "type": "tool_use",
                        "id": "call_1",
                        "name": "create_invoice",
                        "input": {"qty": 5, "rate": 1290},
                    },
                ],
            }
        ]
    )
    message = out[0]
    assert message["content"] == "banata hoon"
    call = message["tool_calls"][0]
    assert call["id"] == "call_1"
    assert json.loads(call["function"]["arguments"]) == {"qty": 5, "rate": 1290}


def test_a_parallel_tool_batch_expands_into_one_tool_message_each():
    """We keep a whole batch in one user turn; OpenAI wants them separate. Losing
    one here would leave a tool_call with no result and the next call 400s."""
    out = to_openai_messages(
        [
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "a", "name": "search_parties", "input": {}},
                    {"type": "tool_use", "id": "b", "name": "search_items", "input": {}},
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "a", "content": '{"ok":true}'},
                    {"type": "tool_result", "tool_use_id": "b", "content": '{"ok":true}'},
                ],
            },
        ]
    )
    assert [m["role"] for m in out] == ["assistant", "tool", "tool"]
    assert [m["tool_call_id"] for m in out[1:]] == ["a", "b"]


def test_tool_results_that_are_not_strings_are_json_encoded():
    out = to_openai_messages(
        [
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "a", "content": {"total": 6450}}
                ],
            }
        ]
    )
    assert json.loads(out[0]["content"]) == {"total": 6450}


def test_an_image_block_degrades_to_a_note_instead_of_vanishing():
    """No vision on this plan. Dropping the block silently would leave a user
    turn with no content at all, which the API rejects."""
    out = to_openai_messages(
        [
            {
                "role": "user",
                "content": [
                    {"type": "image", "source": {"data": "..."}},
                    {"type": "text", "text": "ye bill dekho"},
                ],
            }
        ]
    )
    assert len(out) == 1
    assert "could not be read" in out[0]["content"]
    assert "ye bill dekho" in out[0]["content"]


# ── responses: OpenAI → our blocks ───────────────────────────────
def test_a_tool_call_response_becomes_tool_use_blocks():
    result = _normalise(
        {
            "model": "openai/gpt-oss-120b",
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_9",
                                "function": {
                                    "name": "create_invoice",
                                    "arguments": '{"qty":5}',
                                },
                            }
                        ],
                    },
                }
            ],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20},
        },
        latency_ms=42,
    )

    assert result.stop_reason == "tool_use"
    assert result.tool_uses[0]["name"] == "create_invoice"
    assert result.tool_uses[0]["input"] == {"qty": 5}
    assert (result.input_tokens, result.output_tokens) == (100, 20)


def test_finish_reasons_map_onto_the_app_vocabulary():
    def stop_reason(finish: str) -> str | None:
        return _normalise(
            {"choices": [{"finish_reason": finish, "message": {"content": "x"}}]}, 0
        ).stop_reason

    assert stop_reason("stop") == "end_turn"
    assert stop_reason("length") == "max_tokens"
    assert stop_reason("content_filter") == "refusal"


def test_a_content_filter_stop_is_treated_as_a_refusal():
    result = _normalise(
        {"choices": [{"finish_reason": "content_filter", "message": {"content": ""}}]}, 0
    )
    assert result.is_refusal


def test_malformed_tool_arguments_become_an_empty_object():
    """A truncated JSON string must not crash the tool loop — the executor should
    get `{}` and report a clean validation error instead."""
    assert _parse_arguments('{"qty": 5,') == {}
    assert _parse_arguments("") == {}
    assert _parse_arguments("[1,2]") == {}
    assert _parse_arguments({"qty": 5}) == {"qty": 5}


def test_an_empty_response_does_not_explode():
    result = _normalise({}, 0)
    assert result.text == ""
    assert result.content == []
    assert result.tool_uses == []
