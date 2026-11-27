# agent_loop

A small, real library implementing the agentic loop mechanics described in
"The Loop Is Twelve Lines. Everything Else Is the Argument.": the loop
itself is trivial, but turn accounting, tool scheduling, permission modes,
hooks, and context/compaction are what actually determine behavior.

Building this out in phases — see the project plan for the full breakdown.
**Phase 1 (real model wiring) is done**: `AnthropicModel` drives the loop
against the real Claude Messages API.

Install dependencies:

```
pip install -r requirements.txt
```

Run the scripted demo (no API key needed — uses a mock model):

```
python3 -m agent_loop.demo
```

Run the test suite (mocks the Anthropic client, so no API key or network
access is needed):

```
python3 -m pytest agent_loop/tests -v
```

To drive the loop against the real API instead of the mock, set
`ANTHROPIC_API_KEY` and swap in `AnthropicModel`:

```python
from agent_loop.core import AgentLoop
from agent_loop.anthropic_model import AnthropicModel
from agent_loop.tools import build_tools

tools = build_tools()
loop = AgentLoop(
    AnthropicModel(tools),
    tools,
    system_prompt="You are a coding agent.",
    max_turns=10,
)
result = loop.run("Fix the failing tests in auth.ts")
```

## What it demonstrates

- **`agent_loop/core.py`** — the ~12-line loop (`AgentLoop.run`), plus:
  - turn accounting where only tool-using round trips count (the final
    text-only response is free)
  - `max_turns` / `max_budget_usd` caps that stop the loop mid-task, costing
    money for zero delivered value
  - permission modes (`default`, `acceptEdits`, `plan`, `bypassPermissions`)
    with deny/ask rule precedence
  - `PreToolUse` / `PostToolUse` / `PreCompact` / `Stop` hooks that run
    outside the model's context, at zero token cost
  - a toy context window that triggers compaction, dropping older history
    into a summary — showing why long-lived constraints belong in
    `claude_md` rather than the initial prompt
  - concurrent execution of read-only tool calls vs. sequential execution
    of mutating ones within a single turn

- **`agent_loop/tools.py`** — a fake filesystem and test runner used as
  stand-ins for `Read`/`Write`/`Grep`/`Bash`.

- **`agent_loop/mock_model.py`** — a scripted "model" replaying the
  article's four-turn "fix the failing tests in `auth.ts`" walkthrough, so
  the demo runs with no API key.

- **`agent_loop/anthropic_model.py`** — the real model wiring. Converts the
  loop's tool definitions to the Anthropic Messages API's `input_schema`
  format, flattens the loop's internal history into alternating
  user/assistant messages (translating `tool_use` and `tool_result` blocks
  both ways), and exposes `AnthropicModel` as a drop-in replacement for the
  mock in `AgentLoop`.

- **`agent_loop/tests/`** — `test_core.py` locks down the three demo
  scenarios as regression tests; `test_anthropic_model.py` verifies the
  Claude API adapter (schema conversion, history round-tripping, and a full
  loop run) against a mocked client, so the suite needs no network access
  or API key.

- **`agent_loop/demo.py`** — three runs against the same task:
  1. `max_turns=10`: succeeds in 4 turns.
  2. `max_turns=2`: dies after reading the files and before editing them —
     full cost of understanding the problem, none of the fix.
  3. `permission_mode="plan"`: every mutating tool call is denied, yet the
     model still produces a no-tool-calls response claiming success —
     illustrating that the loop's only exit condition is silence, not
     verified completion.

---

## session_graph

`session_graph/` turns one Claude Code session transcript into a knowledge graph
in Relate and renders it as a radial SVG/PNG. See
[`session_graph/README.md`](session_graph/README.md).

## session_meter

`session_meter/` is a Mac menu-bar widget. It pins a small always-on-top window to a
screen corner and shows the current Claude Code chat as an engine meter and ring graph.
See [`session_meter/README.md`](session_meter/README.md).
