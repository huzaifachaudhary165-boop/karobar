"""The assistant's tool registry, checked as a whole.

Every tool is four separate pieces of bookkeeping: the schema the model reads,
a handler that runs it, a permission it needs, and — for writes — membership of
the set that marks the conversation as having changed something.

Miss one and the failure is quiet and specific. A tool with no handler is
advertised to the model and blows up when it is called. A write missing from
WRITE_TOOLS runs perfectly and leaves the app showing stale figures. A write
with no permission entry is offered to a shop assistant who should not have it.

None of that shows up in a test of any one tool, which is why this checks the
registry rather than the tools.
"""

from __future__ import annotations

import pytest

from app.ai.tools import (
    DESTRUCTIVE_TOOLS, TOOL_PERMISSION, TOOLS, WRITE_TOOLS, ToolExecutor,
    available_tools,
)

_NAMES = [t["name"] for t in TOOLS]


def test_every_tool_has_a_handler():
    missing = [n for n in _NAMES if not hasattr(ToolExecutor, f"_t_{n}")]
    assert not missing, f"advertised to the model with nothing behind them: {missing}"


def test_every_tool_says_what_permission_it_needs():
    missing = [n for n in _NAMES if n not in TOOL_PERMISSION]
    assert not missing, f"no permission, so offered to everybody: {missing}"


def test_every_write_tool_is_marked_as_one():
    """The app refreshes its cached lists off this set.

    A write that is not in it succeeds and leaves the shopkeeper looking at the
    figures from before their own change.
    """
    writes = {n for n in _NAMES if n.startswith(("create_", "update_", "delete_"))}
    writes |= {"record_payment", "record_expense", "adjust_stock", "cancel_invoice"}

    missing = writes - WRITE_TOOLS
    assert not missing, f"writes not marked as writes: {missing}"


def test_nothing_is_marked_a_write_that_no_longer_exists():
    assert WRITE_TOOLS <= set(_NAMES)
    assert DESTRUCTIVE_TOOLS <= WRITE_TOOLS


def test_names_are_unique():
    assert len(_NAMES) == len(set(_NAMES))


def test_each_schema_is_shaped_the_way_the_model_expects():
    for tool in TOOLS:
        schema = tool["input_schema"]
        assert tool.get("description"), f"{tool['name']} has no description"
        assert schema["type"] == "object", tool["name"]
        assert schema.get("additionalProperties") is False, (
            f"{tool['name']} would accept invented arguments"
        )
        for required in schema.get("required", []):
            assert required in schema["properties"], (
                f"{tool['name']} requires '{required}' but never defines it"
            )


# ── what the deleting tools can reach ──────────────────────────────
def test_deleting_needs_a_delete_permission():
    """Not a write permission.

    Someone trusted to raise a bill is not automatically trusted to make one
    disappear, and the roles already draw that line.
    """
    for name in DESTRUCTIVE_TOOLS:
        assert TOOL_PERMISSION[name].value.endswith(":delete"), name


def test_a_deleting_tool_tells_the_model_to_confirm_first():
    for name in DESTRUCTIVE_TOOLS:
        tool = next(t for t in TOOLS if t["name"] == name)
        assert "confirm" in tool["description"].lower(), (
            f"{name} does not tell the model to ask the shopkeeper first"
        )


def test_deleting_a_bill_says_how_it_differs_from_cancelling():
    """The two are different answers to different questions, and the model has
    to pick. Cancelling keeps a bill that really happened; deleting removes one
    that should never have existed."""
    tool = next(t for t in TOOLS if t["name"] == "delete_invoice")
    assert "cancel_invoice" in tool["description"]


# ── who gets offered what ──────────────────────────────────────────
@pytest.mark.parametrize("role", ["owner", "admin"])
def test_an_owner_is_offered_the_deleting_tools(role):
    offered = {t["name"] for t in available_tools(role)}
    assert DESTRUCTIVE_TOOLS <= offered, f"{role} cannot reach: {DESTRUCTIVE_TOOLS - offered}"


def test_a_read_only_conversation_is_offered_no_writes():
    offered = {t["name"] for t in available_tools("owner", allow_writes=False)}
    assert not (offered & WRITE_TOOLS)
    # And still has something useful to do.
    assert "get_business_summary" in offered
