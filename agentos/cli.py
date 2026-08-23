from __future__ import annotations

import sys

import click

from agentos.agent.loop import AgentSession
from agentos.agent.presets import LINT_FIX_SYSTEM_PROMPT, build_lint_task, extract_paths_from_output
from agentos.config import Config
from agentos.llm.client import LLMClient
from agentos.tools.fs import Workspace
from agentos.tools.shell import run_command
from agentos.ui.tui import AgentTUI


@click.group()
def main() -> None:
    """agentos: a terminal coding agent driven by local, multi-GPU LLM inference."""


@main.command()
@click.argument("task")
@click.option("--config", "config_path", default="agentos.yaml", help="Path to config YAML.")
@click.option("--workdir", default=None, help="Project directory to operate on (overrides config).")
@click.option("--no-tui", is_flag=True, help="Plain-text output instead of the live GPU/log TUI.")
def run(task: str, config_path: str, workdir: str | None, no_tui: bool) -> None:
    """Run the agent on TASK: edit files, build, iterate until it passes or gives up."""
    config = Config.load(config_path)
    if workdir:
        config.workdir = workdir

    workspace = Workspace(config.workdir)
    client = LLMClient(endpoints=config.endpoints, model=config.model, api_key=config.api_key)

    session = AgentSession(config=config, workspace=workspace, client=client)

    if no_tui:
        _run_plain(session, task)
    else:
        _run_tui(session, task)

    client.close()


def _run_plain(session: AgentSession, task: str, seed_paths: list[str] | None = None) -> None:
    def on_event(kind: str, payload: object) -> None:
        click.echo(f"[{kind}] {payload}")

    session.on_event = on_event
    results = session.run(task, seed_paths=seed_paths)
    final = results[-1] if results else None
    if final and final.done:
        click.echo(click.style("agent finished successfully", fg="green"))
    else:
        click.echo(click.style("agent stopped without confirming success", fg="yellow"))
        sys.exit(1)


def _run_tui(session: AgentSession, task: str, seed_paths: list[str] | None = None) -> None:
    with AgentTUI(tokens_per_sec_fn=session.client.aggregate_tokens_per_sec) as tui:

        def on_event(kind: str, payload: object) -> None:
            if kind == "iteration_start":
                tui.set_status(f"iteration {payload}")
            elif kind == "llm_reply":
                tui.log(f"model replied ({payload.usage.completion_tokens} tok, "
                         f"{payload.usage.tokens_per_sec:.1f} tok/s via {payload.usage.endpoint})")
            elif kind == "patch_applied":
                tui.log(f"applied diff -> {', '.join(payload) or '(no changes)'}")
            elif kind == "patch_error":
                tui.log(f"patch error: {payload.patch_error}")
            elif kind == "build_result":
                status = "OK" if payload.ok else f"FAILED (exit {payload.returncode})"
                tui.log(f"build: {status}")
            elif kind == "done":
                tui.set_status("done")
                tui.log("agent finished")
            tui.refresh()

        session.on_event = on_event
        results = session.run(task, seed_paths=seed_paths)

    final = results[-1] if results else None
    if not (final and final.done):
        sys.exit(1)


@main.command(name="lint-fix")
@click.option("--config", "config_path", default="agentos.yaml", help="Path to config YAML.")
@click.option("--workdir", default=None, help="Project directory to operate on (overrides config).")
@click.option("--lint-cmd", default=None, help="Lint/type-check command (defaults to the config's build_cmd).")
@click.option("--max-iterations", default=4, show_default=True, help="Iteration cap for this narrow-scope agent.")
@click.option("--no-tui", is_flag=True, help="Plain-text output instead of the live GPU/log TUI.")
def lint_fix(
    config_path: str,
    workdir: str | None,
    lint_cmd: str | None,
    max_iterations: int,
    no_tui: bool,
) -> None:
    """Run your lint/type-check command and fix only what it reports.

    The narrowest, safest first agent: the task is generated from the linter's
    own output, only the files it names are touched, and success is exactly
    "the same command now exits 0" — no free-form task string needed.
    """
    config = Config.load(config_path)
    if workdir:
        config.workdir = workdir
    if lint_cmd:
        config.build_cmd = lint_cmd
    if not config.build_cmd:
        raise click.UsageError("no lint command: set build_cmd in agentos.yaml or pass --lint-cmd")
    config.max_iterations = max_iterations

    workspace = Workspace(config.workdir)
    initial = run_command(config.build_cmd, cwd=str(workspace.root))
    if initial.ok:
        click.echo(click.style(f"'{config.build_cmd}' already passes — nothing to fix", fg="green"))
        return

    output = initial.combined_output(max_chars=8000)
    paths = extract_paths_from_output(output, workspace)
    if not paths:
        click.echo(
            "lint command failed but no file paths could be parsed from its output:\n\n"
            f"{output}\n\nrun `agentos run \"<task>\"` manually instead."
        )
        sys.exit(1)

    click.echo(f"found violations in {len(paths)} file(s): {', '.join(paths)}")

    client = LLMClient(endpoints=config.endpoints, model=config.model, api_key=config.api_key)
    session = AgentSession(
        config=config,
        workspace=workspace,
        client=client,
        system_prompt=LINT_FIX_SYSTEM_PROMPT,
    )
    task = build_lint_task(output)

    if no_tui:
        _run_plain(session, task, seed_paths=paths)
    else:
        _run_tui(session, task, seed_paths=paths)

    client.close()


@main.command()
def demo() -> None:
    """Run the live TUI against simulated data — no GPU or model server required."""
    from agentos.demo import run_demo

    run_demo()


@main.command()
@click.option("--config", "config_path", default="agentos.yaml", help="Path to config YAML.")
def gpus(config_path: str) -> None:
    """Print current GPU stats (nvidia-smi) once and exit."""
    from agentos.gpu.monitor import read_gpu_stats

    stats = read_gpu_stats()
    if not stats:
        click.echo("no GPUs detected (is nvidia-smi installed?)")
        return
    for s in stats:
        click.echo(
            f"GPU{s.index} {s.name}: util={s.util_pct:.0f}% "
            f"mem={s.mem_used_mib/1024:.1f}/{s.mem_total_mib/1024:.1f}GiB "
            f"temp={s.temp_c:.0f}C power={s.power_w:.0f}/{s.power_limit_w:.0f}W"
        )


if __name__ == "__main__":
    main()
