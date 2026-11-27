from types import SimpleNamespace
from unittest.mock import MagicMock

from agent_loop.anthropic_model import (
    AnthropicModel,
    claude_response_to_assistant_message,
    history_to_claude_messages,
    tools_to_claude_schema,
)
from agent_loop.core import AgentLoop, AssistantMessage, ToolCall, ToolResult, UserMessage
from agent_loop.tools import build_tools, reset_fs


def _text_block(text):
    return SimpleNamespace(type="text", text=text)


def _tool_use_block(id_, name, input_):
    return SimpleNamespace(type="tool_use", id=id_, name=name, input=input_)


def test_tools_to_claude_schema_carries_description_and_input_schema():
    schema = tools_to_claude_schema(build_tools())
    names = {t["name"] for t in schema}
    assert names == {"Read", "Grep", "Write", "Bash"}
    read_schema = next(t for t in schema if t["name"] == "Read")
    assert read_schema["input_schema"]["properties"]["path"]["type"] == "string"
    assert read_schema["description"]


def test_history_to_claude_messages_round_trips_tool_use_and_result():
    history = [
        ("user_prompt", "Fix the bug"),
        AssistantMessage(text="", tool_calls=[ToolCall("Bash", {"command": "npm test"}, id="call_1")]),
        UserMessage([ToolResult(ToolCall("Bash", {"command": "npm test"}, id="call_1"), "0 passed, 3 failed")]),
    ]
    messages = history_to_claude_messages(history)
    assert [m["role"] for m in messages] == ["user", "assistant", "user"]
    assert messages[1]["content"][0] == {
        "type": "tool_use",
        "id": "call_1",
        "name": "Bash",
        "input": {"command": "npm test"},
    }
    assert messages[2]["content"][0] == {
        "type": "tool_result",
        "tool_use_id": "call_1",
        "content": "0 passed, 3 failed",
    }


def test_claude_response_to_assistant_message_splits_text_and_tool_use():
    response = SimpleNamespace(
        content=[_text_block("Let me check."), _tool_use_block("call_9", "Read", {"path": "auth.ts"})]
    )
    msg = claude_response_to_assistant_message(response)
    assert msg.text == "Let me check."
    assert msg.tool_calls == [ToolCall("Read", {"path": "auth.ts"}, id="call_9")]


def test_anthropic_model_drives_the_real_loop_end_to_end():
    reset_fs()
    tools = build_tools()
    client = MagicMock()
    client.messages.create.side_effect = [
        SimpleNamespace(content=[_tool_use_block("call_1", "Bash", {"command": "npm test"})]),
        SimpleNamespace(content=[_text_block("Tests are still failing; stopping here for this test.")]),
    ]
    model = AnthropicModel(tools, client=client)
    loop = AgentLoop(model, tools, system_prompt="You are a coding agent.", max_turns=5)

    result = loop.run("Fix the failing tests in auth.ts")

    assert result.subtype == "success"
    assert result.turns == 1
    assert client.messages.create.call_count == 2

    first_call_kwargs = client.messages.create.call_args_list[0].kwargs
    assert first_call_kwargs["system"] == "You are a coding agent."
    assert {t["name"] for t in first_call_kwargs["tools"]} == {"Read", "Grep", "Write", "Bash"}

    second_call_kwargs = client.messages.create.call_args_list[1].kwargs
    roles = [m["role"] for m in second_call_kwargs["messages"]]
    assert roles == ["user", "assistant", "user"]
