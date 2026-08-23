"""A scripted stand-in for the LLM: replays the article's 'fix the failing tests
in auth.ts' walkthrough turn-by-turn so the loop mechanics can run with no API key."""

from .core import AssistantMessage, ToolCall, UserMessage


def scripted_model():
    step = {"n": 0}

    def model(system_prompt, tools, history) -> AssistantMessage:
        step["n"] += 1
        n = step["n"]

        if n == 1:
            return AssistantMessage(
                text="Let me check what's failing.",
                tool_calls=[ToolCall("Bash", {"command": "npm test"})],
            )
        if n == 2:
            return AssistantMessage(
                text="Reading the source and the test.",
                tool_calls=[
                    ToolCall("Read", {"path": "auth.ts"}),
                    ToolCall("Read", {"path": "auth.test.ts"}),
                ],
            )
        if n == 3:
            return AssistantMessage(
                text="Fixing the login function and re-running tests.",
                tool_calls=[
                    ToolCall(
                        "Write",
                        {
                            "path": "auth.ts",
                            "content": "function login(user, pass) {\n"
                            "  return user.password === pass;\n"
                            "}\n",
                        },
                    ),
                ],
            )
        if n == 4:
            last = history[-1]
            assert isinstance(last, UserMessage)
            return AssistantMessage(
                text="Confirming the fix.",
                tool_calls=[ToolCall("Bash", {"command": "npm test"})],
            )
        return AssistantMessage(text="All three tests pass. auth.ts is fixed.", tool_calls=[])

    return model
