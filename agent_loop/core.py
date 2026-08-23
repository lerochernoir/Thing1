"""Minimal agentic loop with the mechanics the surrounding framework leaves implicit:
turn accounting, budget caps, permission modes, hooks, and context-window/compaction."""

from __future__ import annotations

import concurrent.futures
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class ToolCall:
    name: str
    args: dict


@dataclass
class ToolResult:
    call: ToolCall
    output: str
    cost_usd: float = 0.0


@dataclass
class AssistantMessage:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)


@dataclass
class UserMessage:
    results: list[ToolResult]


@dataclass
class SystemMessage:
    kind: str  # "init" | "compact_boundary" | "worker_shutting_down"
    detail: str = ""


@dataclass
class ResultMessage:
    subtype: str  # "success" | "error_max_turns" | "error_max_budget_usd" | "error_during_execution"
    text: str | None
    turns: int
    cost_usd: float


class HookAbort(Exception):
    """Raised by a hook to veto the action it's guarding."""


class PermissionDenied(Exception):
    pass


PERMISSION_MODES = ("default", "acceptEdits", "plan", "bypassPermissions")


class Tool:
    def __init__(self, name: str, read_only: bool, fn: Callable[[dict], str], cost_usd: float = 0.0):
        self.name = name
        self.read_only = read_only
        self.fn = fn
        self.cost_usd = cost_usd


class AgentLoop:
    """The twelve-line loop, with everything the article says actually decides the outcome
    bolted on as explicit, inspectable state rather than left to prompt wording."""

    CONTEXT_WINDOW_TOKENS = 2000  # deliberately small so the demo triggers compaction

    def __init__(
        self,
        model,
        tools: dict[str, Tool],
        *,
        system_prompt: str,
        claude_md: str = "",
        max_turns: int | None = None,
        max_budget_usd: float | None = None,
        permission_mode: str = "default",
        ask_rules: tuple[str, ...] = (),
        deny_rules: tuple[str, ...] = (),
    ):
        assert permission_mode in PERMISSION_MODES
        self.model = model
        self.tools = tools
        self.system_prompt = system_prompt
        self.claude_md = claude_md
        self.max_turns = max_turns
        self.max_budget_usd = max_budget_usd
        self.permission_mode = permission_mode
        self.ask_rules = ask_rules
        self.deny_rules = deny_rules

        self.history: list[object] = []
        self.stream: list[object] = []
        self.hooks: dict[str, list[Callable]] = {
            "PreToolUse": [], "PostToolUse": [], "PreCompact": [], "Stop": [],
        }
        self.turns = 0
        self.cost_usd = 0.0
        self._tokens_used = 0

    def on(self, event: str, fn: Callable):
        self.hooks[event].append(fn)
        return fn

    def _emit(self, msg):
        self.stream.append(msg)

    def _estimate_tokens(self, obj) -> int:
        return len(repr(obj)) // 3

    def _context_payload(self) -> str:
        return self.system_prompt + self.claude_md + "".join(repr(m) for m in self.history)

    def _maybe_compact(self):
        used = self._estimate_tokens(self._context_payload())
        if used < self.CONTEXT_WINDOW_TOKENS:
            return
        for hook in self.hooks["PreCompact"]:
            hook(trigger="automatic", history=list(self.history))
        kept = self.history[-2:]
        summary = f"[compacted summary of {len(self.history) - len(kept)} earlier messages]"
        self.history = [SystemMessage("compact_boundary", summary)] + kept
        self._emit(SystemMessage("compact_boundary", summary))

    def _check_permission(self, call: ToolCall, tool: Tool) -> str:
        for rule in self.deny_rules:
            if rule == call.name:
                raise PermissionDenied(f"{call.name} matched deny rule")
        for rule in self.ask_rules:
            if rule == call.name:
                return "ask"
        if self.permission_mode == "plan" and not tool.read_only:
            raise PermissionDenied("plan mode: mutating tools are blocked")
        if self.permission_mode == "bypassPermissions":
            return "allow"
        if self.permission_mode == "acceptEdits" and not tool.read_only:
            return "allow"
        if self.permission_mode == "default":
            return "ask" if not tool.read_only else "allow"
        return "allow"

    def _execute(self, calls: list[ToolCall]) -> list[ToolResult]:
        approved = []
        for call in calls:
            tool = self.tools[call.name]
            decision = self._check_permission(call, tool)
            if decision == "ask":
                pass  # in a real UI this blocks for a human; the demo auto-approves
            for hook in self.hooks["PreToolUse"]:
                hook(call)
            approved.append((call, tool))

        read_only = [(c, t) for c, t in approved if t.read_only]
        mutating = [(c, t) for c, t in approved if not t.read_only]

        results: list[ToolResult] = []

        def run(pair):
            call, tool = pair
            output = tool.fn(call.args)
            return ToolResult(call, output, tool.cost_usd)

        if read_only:
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(read_only)) as pool:
                results.extend(pool.map(run, read_only))
        for pair in mutating:
            results.append(run(pair))

        for r in results:
            for hook in self.hooks["PostToolUse"]:
                hook(r)
        return results

    def run(self, user_prompt: str) -> ResultMessage:
        self._emit(SystemMessage("init", "session started"))
        self.history.append(("user_prompt", user_prompt))

        while True:
            if self.max_turns is not None and self.turns >= self.max_turns:
                result = ResultMessage("error_max_turns", None, self.turns, self.cost_usd)
                self._emit(result)
                return result
            if self.max_budget_usd is not None and self.cost_usd >= self.max_budget_usd:
                result = ResultMessage("error_max_budget_usd", None, self.turns, self.cost_usd)
                self._emit(result)
                return result

            response: AssistantMessage = self.model(self.history)
            self.history.append(response)
            self._emit(response)

            if not response.tool_calls:
                for hook in self.hooks["Stop"]:
                    verdict = hook(response)
                    if verdict is False:
                        raise HookAbort("Stop hook rejected completion")
                result = ResultMessage("success", response.text, self.turns, self.cost_usd)
                self._emit(result)
                return result

            self.turns += 1  # a turn is a round trip that used tools; the final text is free
            try:
                results = self._execute(response.tool_calls)
            except (PermissionDenied, HookAbort) as e:
                results = [ToolResult(c, f"DENIED: {e}") for c in response.tool_calls]

            self.cost_usd += sum(r.cost_usd for r in results)
            msg = UserMessage(results)
            self.history.append(msg)
            self._emit(msg)
            self._maybe_compact()
