"""Rich-based terminal UI: build/agent log on the left, GPU panels on the right."""
from __future__ import annotations

from typing import Callable

from rich.console import Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.progress_bar import ProgressBar
from rich.table import Table
from rich.text import Text

from agentos.gpu.monitor import GpuStat, read_gpu_stats


class AgentTUI:
    """Live log + GPU panel display.

    `gpu_stats_fn` and `tokens_per_sec_fn` default to real `nvidia-smi` and
    LLM-client throughput sources; pass alternates (e.g. from `demo.py`) to
    drive the same UI from simulated data without a GPU or model server.
    """

    def __init__(
        self,
        title: str = "agentos",
        *,
        gpu_stats_fn: Callable[[], list[GpuStat]] = read_gpu_stats,
        tokens_per_sec_fn: Callable[[], float] = lambda: 0.0,
    ):
        self.title = title
        self._gpu_stats_fn = gpu_stats_fn
        self._tokens_per_sec_fn = tokens_per_sec_fn
        self.log_lines: list[str] = []
        self.status = "starting"
        self.layout = Layout()
        self.layout.split_row(
            Layout(name="log", ratio=2),
            Layout(name="gpu", ratio=1),
        )
        self._live: Live | None = None

    def log(self, line: str) -> None:
        self.log_lines.append(line)
        self.log_lines = self.log_lines[-500:]
        if self._live:
            self._live.update(self._render())

    def set_status(self, status: str) -> None:
        self.status = status
        if self._live:
            self._live.update(self._render())

    def __enter__(self) -> "AgentTUI":
        self._live = Live(self._render(), refresh_per_second=4, screen=False)
        self._live.__enter__()
        return self

    def __exit__(self, *exc) -> None:
        if self._live:
            self._live.update(self._render())
            self._live.__exit__(*exc)

    def refresh(self) -> None:
        if self._live:
            self._live.update(self._render())

    def _render_log_panel(self) -> Panel:
        tail = self.log_lines[-40:]
        body = Text("\n".join(tail) or "(waiting for agent output)")
        return Panel(body, title=f"{self.title} — {self.status}", border_style="cyan")

    def _render_gpu_panel(self) -> Panel:
        stats = self._gpu_stats_fn()
        tps = self._tokens_per_sec_fn()

        header = Text(f"{tps:,.1f} tok/s aggregate\n", style="bold green")
        if not stats:
            return Panel(Group(header, Text("nvidia-smi unavailable", style="dim")), title="GPUs", border_style="magenta")

        rows = [header]
        for s in stats:
            rows.append(self._gpu_row(s))
        return Panel(Group(*rows), title="GPUs", border_style="magenta")

    def _gpu_row(self, s: GpuStat) -> Group:
        util_bar = ProgressBar(total=100, completed=s.util_pct, width=20)
        mem_bar = ProgressBar(total=100, completed=s.mem_pct, width=20)
        label = Text(f"GPU{s.index} {s.name}  {s.temp_c:.0f}C  {s.power_w:.0f}/{s.power_limit_w:.0f}W")
        table = Table.grid(padding=(0, 1))
        table.add_row(Text("util"), util_bar, Text(f"{s.util_pct:.0f}%"))
        table.add_row(Text("mem "), mem_bar, Text(f"{s.mem_used_mib/1024:.1f}/{s.mem_total_mib/1024:.1f} GiB"))
        return Group(label, table)

    def _render(self):
        self.layout["log"].update(self._render_log_panel())
        self.layout["gpu"].update(self._render_gpu_panel())
        return self.layout
