# agent_loop

A runnable demo of the agentic loop mechanics described in "The Loop Is Twelve
Lines. Everything Else Is the Argument.": the loop itself is trivial, but
turn accounting, tool scheduling, permission modes, hooks, and context/
compaction are what actually determine behavior.

Run it:

```
python3 -m agent_loop.demo
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

- **`agent_loop/demo.py`** — three runs against the same task:
  1. `max_turns=10`: succeeds in 4 turns.
  2. `max_turns=2`: dies after reading the files and before editing them —
     full cost of understanding the problem, none of the fix.
  3. `permission_mode="plan"`: every mutating tool call is denied, yet the
     model still produces a no-tool-calls response claiming success —
     illustrating that the loop's only exit condition is silence, not
     verified completion.
