"""GPU monitoring via `nvidia-smi`, no extra Python bindings required."""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

QUERY_FIELDS = [
    "index",
    "name",
    "utilization.gpu",
    "memory.used",
    "memory.total",
    "temperature.gpu",
    "power.draw",
    "power.limit",
]


@dataclass
class GpuStat:
    index: int
    name: str
    util_pct: float
    mem_used_mib: float
    mem_total_mib: float
    temp_c: float
    power_w: float
    power_limit_w: float

    @property
    def mem_pct(self) -> float:
        return (self.mem_used_mib / self.mem_total_mib * 100) if self.mem_total_mib else 0.0


def nvidia_smi_available() -> bool:
    return shutil.which("nvidia-smi") is not None


def read_gpu_stats() -> list[GpuStat]:
    """Return current stats for all visible GPUs. Empty list if unavailable."""
    if not nvidia_smi_available():
        return []
    cmd = [
        "nvidia-smi",
        f"--query-gpu={','.join(QUERY_FIELDS)}",
        "--format=csv,noheader,nounits",
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=5, check=True)
    except (subprocess.SubprocessError, OSError):
        return []

    stats: list[GpuStat] = []
    for line in out.stdout.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != len(QUERY_FIELDS):
            continue
        idx, name, util, mem_used, mem_total, temp, power, power_limit = parts
        stats.append(
            GpuStat(
                index=int(idx),
                name=name,
                util_pct=_to_float(util),
                mem_used_mib=_to_float(mem_used),
                mem_total_mib=_to_float(mem_total),
                temp_c=_to_float(temp),
                power_w=_to_float(power),
                power_limit_w=_to_float(power_limit),
            )
        )
    return stats


def _to_float(value: str) -> float:
    try:
        return float(value)
    except ValueError:
        return 0.0
