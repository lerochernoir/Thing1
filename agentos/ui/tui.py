"""Rich-based terminal UI: build/agent log on the left, GPU panels on the right.

Styled after a Bauhaus/Braun instrument panel: flat primary colors per
module (blue = log, red = GPU), heavy high-contrast borders standing in
for the checkerboard frames in the design reference, bold throughout.
"""
from __future__ import annotations

from typing import Callable

from rich import box
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

    # Bauhaus/Braun primary triad — fixed, not theme-dependent.
    RED = "#d1141e"
    BLUE = "#1558a6"
    YELLOW = "#f5c400"

    def _render_log_panel(self) -> Panel:
        tail = self.log_lines[-40:]
        body = Text("\n".join(tail) or "(waiting for agent output)")
        title = Text(f" {self.title.upper()} — {self.status.upper()} ", style=f"bold white on {self.BLUE}")
        return Panel(body, title=title, border_style=f"bold {self.BLUE}", box=box.HEAVY)

    def _render_gpu_panel(self) -> Panel:
        stats = self._gpu_stats_fn()
        tps = self._tokens_per_sec_fn()

        header = Text(f" {tps:,.1f} TOK/S AGGREGATE \n", style=f"bold white on {self.RED}")
        title = Text(" GPUS ", style=f"bold white on {self.RED}")
        if not stats:
            return Panel(
                Group(header, Text("NVIDIA-SMI UNAVAILABLE", style="bold dim")),
                title=title,
                border_style=f"bold {self.RED}",
                box=box.HEAVY,
            )

        rows = [header]
        for s in stats:
            rows.append(self._gpu_row(s))
        return Panel(Group(*rows), title=title, border_style=f"bold {self.RED}", box=box.HEAVY)

    def _gpu_row(self, s: GpuStat) -> Group:
        util_bar = ProgressBar(total=100, completed=s.util_pct, width=20, complete_style=self.RED, finished_style=self.RED)
        mem_bar = ProgressBar(total=100, completed=s.mem_pct, width=20, complete_style=self.BLUE, finished_style=self.BLUE)
        label = Text.from_markup(
            f"[bold white on black] GPU{s.index} [/] [bold]{s.name}[/]  {s.temp_c:.0f}C  {s.power_w:.0f}/{s.power_limit_w:.0f}W"
        )
        table = Table.grid(padding=(0, 1))
        table.add_row(Text("UTIL", style="bold"), util_bar, Text(f"{s.util_pct:.0f}%", style="bold"))
        table.add_row(Text("MEM ", style="bold"), mem_bar, Text(f"{s.mem_used_mib/1024:.1f}/{s.mem_total_mib/1024:.1f} GiB", style="bold"))
        return Group(label, table)

    def _render(self):
        self.layout["log"].update(self._render_log_panel())
        self.layout["gpu"].update(self._render_gpu_panel())
        return self.layout
