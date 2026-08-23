from __future__ import annotations

import sys

import click

from agentos.agent.loop import AgentSession
from agentos.config import Config
from agentos.llm.client import LLMClient
from agentos.tools.fs import Workspace
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


def _run_plain(session: AgentSession, task: str) -> None:
    def on_event(kind: str, payload: object) -> None:
        click.echo(f"[{kind}] {payload}")

    session.on_event = on_event
    results = session.run(task)
    final = results[-1] if results else None
    if final and final.done:
        click.echo(click.style("agent finished successfully", fg="green"))
    else:
        click.echo(click.style("agent stopped without confirming success", fg="yellow"))
        sys.exit(1)


def _run_tui(session: AgentSession, task: str) -> None:
    with AgentTUI(session.client) as tui:

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
        results = session.run(task)

    final = results[-1] if results else None
    if not (final and final.done):
        sys.exit(1)


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
