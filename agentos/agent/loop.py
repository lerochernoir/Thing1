"""The core edit -> build -> verify agent loop."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from agentos.config import Config
from agentos.diffing.diff import PatchError, apply_unified_diff
from agentos.llm.client import LLMClient
from agentos.tools.fs import Workspace
from agentos.tools.shell import CommandResult, run_command
from agentos.agent.prompts import (
    FEEDBACK_TEMPLATE,
    SYSTEM_PROMPT,
    TASK_TEMPLATE,
    render_files_block,
)

DIFF_BLOCK_RE = re.compile(r"```diff\s*\n(.*?)```", re.DOTALL)


@dataclass
class IterationResult:
    iteration: int
    reply: str
    diff_applied: bool
    changed_paths: list[str] = field(default_factory=list)
    patch_error: str | None = None
    build_result: CommandResult | None = None
    done: bool = False


@dataclass
class AgentSession:
    config: Config
    workspace: Workspace
    client: LLMClient
    on_event: Callable[[str, object], None] | None = None
    system_prompt: str = SYSTEM_PROMPT

    def _emit(self, kind: str, payload: object) -> None:
        if self.on_event:
            self.on_event(kind, payload)

    def run(self, task: str, seed_paths: list[str] | None = None) -> list[IterationResult]:
        seed_paths = seed_paths or self.workspace.list_files()
        files = self.workspace.read_many(seed_paths)

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": TASK_TEMPLATE.format(task=task, files_block=render_files_block(files))},
        ]

        results: list[IterationResult] = []

        for iteration in range(1, self.config.max_iterations + 1):
            self._emit("iteration_start", iteration)
            chat_result = self.client.chat(
                messages,
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
            )
            self._emit("llm_reply", chat_result)
            reply = chat_result.content

            if reply.strip().upper().startswith("DONE"):
                result = IterationResult(iteration=iteration, reply=reply, diff_applied=False, done=True)
                results.append(result)
                self._emit("done", result)
                break

            match = DIFF_BLOCK_RE.search(reply)
            if not match:
                messages.append({"role": "assistant", "content": reply})
                messages.append(
                    {
                        "role": "user",
                        "content": "No ```diff block found in your reply. Respond with a unified diff in a ```diff block, or DONE.",
                    }
                )
                results.append(IterationResult(iteration=iteration, reply=reply, diff_applied=False))
                continue

            diff_text = match.group(1)
            try:
                current_files = self.workspace.read_many(list(files.keys()))
                updated = apply_unified_diff(current_files, diff_text)
                changed = [p for p in updated if updated.get(p) != current_files.get(p)]
                for path, content in updated.items():
                    self.workspace.write(path, content)
                for removed in set(current_files) - set(updated):
                    self.workspace.delete(removed)
                files = updated
            except PatchError as e:
                result = IterationResult(
                    iteration=iteration, reply=reply, diff_applied=False, patch_error=str(e)
                )
                results.append(result)
                self._emit("patch_error", result)
                messages.append({"role": "assistant", "content": reply})
                messages.append({"role": "user", "content": f"Patch failed to apply: {e}. Please resend a corrected diff."})
                continue

            self._emit("patch_applied", changed)

            build_result = None
            if self.config.build_cmd:
                build_result = run_command(self.config.build_cmd, cwd=str(self.workspace.root))
                self._emit("build_result", build_result)

            result = IterationResult(
                iteration=iteration,
                reply=reply,
                diff_applied=True,
                changed_paths=changed,
                build_result=build_result,
            )
            results.append(result)

            if build_result is None:
                self._emit("done", result)
                break

            if build_result.ok:
                result.done = True
                self._emit("done", result)
                break

            messages.append({"role": "assistant", "content": reply})
            messages.append(
                {
                    "role": "user",
                    "content": FEEDBACK_TEMPLATE.format(
                        iteration=iteration,
                        command=build_result.command,
                        returncode=build_result.returncode,
                        output=build_result.combined_output(),
                        files_block=render_files_block(self.workspace.read_many(list(files.keys()))),
                    ),
                }
            )

        return results
