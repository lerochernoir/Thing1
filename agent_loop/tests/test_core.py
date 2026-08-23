from agent_loop.core import AgentLoop
from agent_loop.mock_model import scripted_model
from agent_loop.tools import build_tools, reset_fs


def test_full_run_fixes_the_file_in_four_turns():
    reset_fs()
    loop = AgentLoop(
        scripted_model(),
        build_tools(),
        system_prompt="You are a coding agent.",
        max_turns=10,
        permission_mode="acceptEdits",
    )
    result = loop.run("Fix the failing tests in auth.ts")
    assert result.subtype == "success"
    assert result.turns == 4


def test_max_turns_stops_before_the_fix_lands():
    reset_fs()
    loop = AgentLoop(
        scripted_model(),
        build_tools(),
        system_prompt="You are a coding agent.",
        max_turns=2,
        permission_mode="acceptEdits",
    )
    result = loop.run("Fix the failing tests in auth.ts")
    assert result.subtype == "error_max_turns"
    assert result.turns == 2


def test_plan_mode_blocks_every_mutation():
    reset_fs()
    loop = AgentLoop(
        scripted_model(),
        build_tools(),
        system_prompt="You are a coding agent.",
        max_turns=10,
        permission_mode="plan",
    )
    result = loop.run("Fix the failing tests in auth.ts")
    assert result.subtype == "success"
    denied = [
        r
        for msg in loop.history
        if hasattr(msg, "results")
        for r in msg.results
        if r.output.startswith("DENIED")
    ]
    assert len(denied) == 3
