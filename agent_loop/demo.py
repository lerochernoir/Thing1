from .core import AgentLoop, ResultMessage, SystemMessage, AssistantMessage, UserMessage
from .mock_model import scripted_model
from .tools import build_tools, TESTS_FIXED, reset_fs


def _print_stream(loop: AgentLoop):
    for msg in loop.stream:
        if isinstance(msg, SystemMessage):
            print(f"  [system:{msg.kind}] {msg.detail}")
        elif isinstance(msg, AssistantMessage):
            calls = ", ".join(c.name for c in msg.tool_calls) or "(none)"
            print(f"  [assistant] {msg.text!r} tool_calls=[{calls}]")
        elif isinstance(msg, UserMessage):
            for r in msg.results:
                print(f"  [tool_result] {r.call.name} -> {r.output!r} (${r.cost_usd:.4f})")
        elif isinstance(msg, ResultMessage):
            print(f"  [result:{msg.subtype}] text={msg.text!r} turns={msg.turns} cost=${msg.cost_usd:.4f}")


def run_full():
    print("=== Full run: max_turns=10 ===")
    reset_fs()
    loop = AgentLoop(
        scripted_model(),
        build_tools(),
        system_prompt="You are a coding agent.",
        claude_md="Never modify files under /legacy.",
        max_turns=10,
        max_budget_usd=1.00,
        permission_mode="acceptEdits",
    )
    loop.on("PreToolUse", lambda call: print(f"  (hook) PreToolUse: about to run {call.name}"))
    loop.on("Stop", lambda msg: print("  (hook) Stop: verifying completion") or True)
    result = loop.run("Fix the failing tests in auth.ts")
    _print_stream(loop)
    print()


def run_capped():
    print("=== Same task, max_turns=2: the footgun ===")
    reset_fs()
    loop = AgentLoop(
        scripted_model(),
        build_tools(),
        system_prompt="You are a coding agent.",
        max_turns=2,
        permission_mode="acceptEdits",
    )
    result = loop.run("Fix the failing tests in auth.ts")
    _print_stream(loop)
    print(f"  -> auth.ts actually fixed on disk? {TESTS_FIXED['value']}")
    print()


def run_plan_mode():
    print("=== plan mode: mutating tools are blocked ===")
    reset_fs()
    loop = AgentLoop(
        scripted_model(),
        build_tools(),
        system_prompt="You are a coding agent.",
        max_turns=10,
        permission_mode="plan",
    )
    result = loop.run("Fix the failing tests in auth.ts")
    _print_stream(loop)
    print(f"  -> auth.ts actually fixed on disk? {TESTS_FIXED['value']}")
    print()


if __name__ == "__main__":
    run_full()
    run_capped()
    run_plan_mode()
