"""Run build/test commands and capture output for feedback to the model."""
from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass


@dataclass
class CommandResult:
    command: str
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def combined_output(self, max_chars: int = 4000) -> str:
        text = (self.stdout + self.stderr).strip()
        if len(text) > max_chars:
            text = text[-max_chars:]
            text = "...(truncated)...\n" + text
        return text


def run_command(command: str, cwd: str, timeout: float = 300.0) -> CommandResult:
    try:
        proc = subprocess.run(
            shlex.split(command),
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return CommandResult(command=command, returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)
    except subprocess.TimeoutExpired as e:
        return CommandResult(
            command=command,
            returncode=-1,
            stdout=(e.stdout or ""),
            stderr=f"command timed out after {timeout}s",
        )
    except FileNotFoundError as e:
        return CommandResult(command=command, returncode=127, stdout="", stderr=str(e))
