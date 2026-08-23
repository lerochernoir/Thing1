"""Phase 1: real model wiring.

Adapts the loop's internal message types to the Anthropic Messages API's
tool-use format, so `AnthropicModel` can be dropped in anywhere `AgentLoop`
expects a `model(system_prompt, tools, history)` callable — replacing the
scripted mock used elsewhere in this package.
"""

from __future__ import annotations

from .core import AssistantMessage, SystemMessage, Tool, ToolCall, ToolResult, UserMessage

try:
    import anthropic
except ImportError:  # pragma: no cover - exercised via RuntimeError below
    anthropic = None

DEFAULT_MODEL = "claude-sonnet-4-5"
DEFAULT_MAX_TOKENS = 4096


def tools_to_claude_schema(tools: dict[str, Tool]) -> list[dict]:
    return [
        {"name": tool.name, "description": tool.description, "input_schema": tool.input_schema}
        for tool in tools.values()
    ]


def _tool_result_block(result: ToolResult) -> dict:
    return {"type": "tool_result", "tool_use_id": result.call.id, "content": result.output}


def history_to_claude_messages(history: list) -> list[dict]:
    """Flattens the loop's internal history — the initial prompt tuple,
    AssistantMessage, UserMessage, and SystemMessage entries — into the
    alternating user/assistant message list the Messages API expects.
    SystemMessage entries are lifecycle bookkeeping, not model-visible turns,
    so they're skipped here."""
    messages: list[dict] = []
    for entry in history:
        if isinstance(entry, tuple) and entry[:1] == ("user_prompt",):
            messages.append({"role": "user", "content": [{"type": "text", "text": entry[1]}]})
        elif isinstance(entry, AssistantMessage):
            content = []
            if entry.text:
                content.append({"type": "text", "text": entry.text})
            for call in entry.tool_calls:
                content.append({"type": "tool_use", "id": call.id, "name": call.name, "input": call.args})
            messages.append({"role": "assistant", "content": content})
        elif isinstance(entry, UserMessage):
            messages.append({"role": "user", "content": [_tool_result_block(r) for r in entry.results]})
        elif isinstance(entry, SystemMessage):
            continue
    return messages


def claude_response_to_assistant_message(response) -> AssistantMessage:
    text_parts = []
    tool_calls = []
    for block in response.content:
        if block.type == "text":
            text_parts.append(block.text)
        elif block.type == "tool_use":
            tool_calls.append(ToolCall(name=block.name, args=block.input, id=block.id))
    return AssistantMessage(text="".join(text_parts), tool_calls=tool_calls)


class AnthropicModel:
    """A `model(system_prompt, tools, history)` callable backed by the real
    Anthropic API. Pass a pre-built `client` (e.g. a mock) for testing;
    otherwise it reads credentials the same way `anthropic.Anthropic()` does."""

    def __init__(
        self,
        tools: dict[str, Tool],
        *,
        model: str = DEFAULT_MODEL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        client=None,
    ):
        if client is None:
            if anthropic is None:
                raise RuntimeError("pip install anthropic to use AnthropicModel without an injected client")
            client = anthropic.Anthropic()
        self.client = client
        self.model = model
        self.max_tokens = max_tokens
        self.claude_tools = tools_to_claude_schema(tools)

    def __call__(self, system_prompt: str, tools: dict[str, Tool], history: list) -> AssistantMessage:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system_prompt,
            tools=self.claude_tools,
            messages=history_to_claude_messages(history),
        )
        return claude_response_to_assistant_message(response)
