"""Simulated agent run for trying the TUI without a GPU or model server.

Drives `AgentTUI` with scripted log events and synthetic GPU stats so the
layout, panels, and diff rendering can be reviewed end-to-end offline.
"""
from __future__ import annotations

import math
import time

from agentos.gpu.monitor import GpuStat
from agentos.ui.tui import AgentTUI

_GPU_NAMES = ["RTX 6000 Ada"] * 4
_START = time.monotonic()

_SCRIPT: list[tuple[float, str]] = [
    (0.0, "[iter 1] read 6 files, 812 tokens of context sent to :8000"),
    (1.1, "model replied — 244 tok · 61.2 tok/s via 127.0.0.1:8000"),
    (0.4, "applied diff -> auth/validators.py"),
    (0.8, "build: FAILED (exit 1) — ValueError: email missing @"),
    (1.0, "[iter 2] feeding pytest output back, 3 files in context"),
    (1.3, "model replied — 268 tok · 64.7 tok/s via 127.0.0.1:8002"),
    (0.4, "applied diff -> auth/validators.py"),
    (0.9, "build: FAILED (exit 1) — 1 assertion, test_password_too_short"),
    (1.0, "[iter 3] feeding pytest output back, 3 files in context"),
    (1.2, "model replied — 96 tok · 58.9 tok/s via 127.0.0.1:8001"),
    (0.3, "applied diff -> auth/validators.py"),
    (0.9, "build: OK"),
    (0.3, "agent finished"),
]


def _fake_gpu_stats(t: float) -> list[GpuStat]:
    stats = []
    for i in range(4):
        phase = i * 0.6
        util = 60 + 35 * abs(math.sin(t * 0.5 + phase))
        mem = 38.5 + 0.6 * math.sin(t * 0.2 + phase)
        temp = 71 + 4 * abs(math.sin(t * 0.3 + phase))
        power = 90 + 20 * abs(math.sin(t * 0.4 + phase))
        stats.append(
            GpuStat(
                index=i,
                name=_GPU_NAMES[i],
                util_pct=util,
                mem_used_mib=mem * 1024,
                mem_total_mib=76.6 * 1024,
                temp_c=temp,
                power_w=power,
                power_limit_w=300.0,
            )
        )
    return stats


def _fake_tokens_per_sec(t: float) -> float:
    return 2400 + 400 * abs(math.sin(t * 0.5))


def run_demo() -> None:
    def gpu_stats_fn() -> list[GpuStat]:
        return _fake_gpu_stats(time.monotonic() - _START)

    def tps_fn() -> float:
        return _fake_tokens_per_sec(time.monotonic() - _START)

    with AgentTUI(gpu_stats_fn=gpu_stats_fn, tokens_per_sec_fn=tps_fn) as tui:
        tui.set_status("demo — add input validation to the login handler")
        deadline = time.monotonic()
        for delay, line in _SCRIPT:
            deadline += delay
            while time.monotonic() < deadline:
                tui.refresh()
                time.sleep(0.1)
            tui.log(line)
        tui.set_status("done")
        end = time.monotonic() + 2.0
        while time.monotonic() < end:
            tui.refresh()
            time.sleep(0.1)
