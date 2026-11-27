#!/usr/bin/env python3
"""Step 1 — extract: Claude Code session JSONL -> normalized JSON.

    python3 extract.py <session.jsonl> [-o out/<uuid>/extract.json]

Reads the main transcript plus any subagent transcripts in
<uuid>/subagents/*.jsonl. Tolerant by design: unknown entry types, unknown
content blocks and missing fields are logged to stderr and skipped, never
raised.

Counting rules (the test re-derives these from the raw log, see README):
  * human turn       = a main-thread `user` entry with typed text (not
                       isMeta, not a tool_result, not a <task-notification>),
                       or a `queued_command` attachment whose prompt is plain
                       text (the user typed while Claude was busy).
  * peer_agent turn  = a subagent result coming back: a <task-notification>
                       or <agent-message> delivery, or an Agent/Task
                       tool_result carrying an agentId. One turn per agentId;
                       the delivery that carries the report text wins, and
                       the tool_result stub is used only when nothing else
                       arrived.
  * tool call        = a distinct `tool_use` block id, main or subagent.
  * file             = a distinct path from Read/Write/Edit/MultiEdit/
                       NotebookEdit file_path (or notebook_path), Glob/Grep
                       `path`, or a path-shaped token in a Bash command.
  * skill            = a distinct `skill` input of a Skill tool_use.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from pathlib import Path

from redact import redact

KNOWN_TYPES = {
    "user", "assistant", "attachment", "system", "summary", "ai-title",
    "atis-latch", "last-prompt", "tools-used", "queue-operation",
    "file-history-snapshot", "progress", "custom-title", "tag",
}
AGENT_TOOLS = {"Agent", "Task"}
FILE_INPUT_TOOLS = {"Read", "Write", "Edit", "MultiEdit", "NotebookEdit"}
PATH_INPUT_TOOLS = {"Glob", "Grep", "LS"}
SR_RE = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
AGENT_MSG_RE = re.compile(r'<agent-message from="([^"]+)">', re.S)
TASK_NOTE_RE = re.compile(r"<task-notification>.*?<task-id>([^<]+)</task-id>", re.S)
# Path-shaped tokens in shell commands: absolute, home-relative or ./ ../
# relative, or bare relative paths with a directory and an extension.
BASH_PATH_RE = re.compile(
    r"""(?<![\w@:/.~$-])((?:~|\.{1,2})?/[\w.@+-]+(?:/[\w.@+-]+)*/?|[\w.-]+/[\w./-]*\.\w{1,8})""")
BASH_PATH_DENY = re.compile(r"^/(dev|proc|sys)/|^/tmp$|^/$|^//")

_warned: set[str] = set()


def warn(msg: str) -> None:
    if msg not in _warned:
        _warned.add(msg)
        print(f"[extract] {msg}", file=sys.stderr)


def read_jsonl(path: str):
    with open(path, encoding="utf-8", errors="replace") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError as e:
                warn(f"{os.path.basename(path)}:{lineno}: bad JSON ({e.msg}); skipped")
                continue
            if not isinstance(d, dict):
                warn(f"{os.path.basename(path)}:{lineno}: non-object line; skipped")
                continue
            yield lineno, d


def content_blocks(entry: dict) -> list:
    msg = entry.get("message")
    if not isinstance(msg, dict):
        return []
    c = msg.get("content")
    if isinstance(c, str):
        return [{"type": "text", "text": c}]
    if isinstance(c, list):
        return [b for b in c if isinstance(b, dict)]
    return []


def plain_text(blocks: list) -> str:
    parts = []
    for b in blocks:
        if b.get("type") == "text" and isinstance(b.get("text"), str):
            parts.append(b["text"])
    return SR_RE.sub("", "\n".join(parts)).strip()


def result_text(block: dict) -> str:
    c = block.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "\n".join(x.get("text", "") for x in c if isinstance(x, dict))
    return ""


def summarize_input(name: str, inp) -> str:
    if not isinstance(inp, dict):
        return redact(str(inp))[:160]
    for key in ("description", "file_path", "notebook_path", "pattern", "url",
                "skill", "query", "command", "prompt"):
        v = inp.get(key)
        if isinstance(v, str) and v:
            s = v if key != "command" else v.splitlines()[0] if v else v
            return redact(s)[:160]
    return redact(json.dumps(inp, sort_keys=True))[:160]


def files_from_tool(name: str, inp) -> list[tuple[str, str]]:
    """Return [(path, how)] for one tool_use input."""
    out: list[tuple[str, str]] = []
    if not isinstance(inp, dict):
        return out
    if name in FILE_INPUT_TOOLS:
        for k in ("file_path", "notebook_path"):
            if isinstance(inp.get(k), str) and inp[k]:
                out.append((inp[k], "input"))
    elif name in PATH_INPUT_TOOLS:
        if isinstance(inp.get("path"), str) and inp["path"]:
            out.append((inp["path"], "input"))
    elif name == "Bash" and isinstance(inp.get("command"), str):
        out.extend((p, "bash") for p in bash_paths(inp["command"]))
    return out


def bash_paths(cmd: str) -> list[str]:
    # Drop heredoc bodies and URLs before scanning.
    cmd = re.sub(r"<<-?\s*'?(\w+)'?\n.*?\n\1\b", " ", cmd, flags=re.S)
    cmd = re.sub(r"\w+://\S+", " ", cmd)
    # A leading `cd /abs/dir &&` lets relative paths resolve.
    m0 = re.match(r"\s*cd\s+(/[^\s;&|]+)\s*(?:&&|;)", cmd)
    base = m0.group(1) if m0 else None
    if m0:
        cmd = cmd[m0.end():]
    seen, out = set(), []
    for m in BASH_PATH_RE.finditer(cmd):
        p = m.group(1).rstrip("/.,;:)\"'") or m.group(1)
        if base and not p.startswith(("/", "~")):
            p = os.path.normpath(os.path.join(base, p))
        if len(p) < 3 or BASH_PATH_DENY.search(p) or p in seen:
            continue
        seen.add(p)
        out.append(p)
    return out


def ts_key(entry: dict, fallback: int) -> tuple:
    return (entry.get("timestamp") or "", fallback)


class Extractor:
    def __init__(self, session_path: str):
        self.session_path = session_path
        _warned.clear()  # warnings are de-duplicated per run, not per process
        self.session_id = Path(session_path).stem
        self.turns: list[dict] = []
        self.calls: dict[str, dict] = {}
        self.results: dict[str, dict] = {}
        self.replies: list[tuple[str, int, str]] = []  # (ts, order, text)
        self.agent_calls: dict[str, str] = {}  # agentId -> Agent tool_use id
        self.peer_by_agent: dict[str, dict] = {}
        self.skipped: dict[str, int] = {}
        self.meta: dict = {}
        self._order = 0

    def _next(self) -> int:
        self._order += 1
        return self._order

    # ---- main thread ------------------------------------------------------
    def read_main(self) -> None:
        for lineno, e in read_jsonl(self.session_path):
            t = e.get("type")
            if t not in KNOWN_TYPES:
                warn(f"unknown entry type {t!r} (line {lineno}); skipped")
                self.skipped[str(t)] = self.skipped.get(str(t), 0) + 1
                continue
            for k in ("cwd", "gitBranch", "version", "entrypoint"):
                if e.get(k) and k not in self.meta:
                    self.meta[k] = e[k]
            if t == "ai-title" and e.get("aiTitle"):
                self.meta["title"] = e["aiTitle"]
            if e.get("isSidechain"):
                # Older Claude Code versions inlined subagent traffic here.
                self._read_tools(e, agent_id=e.get("agentId") or "sidechain")
                continue
            if t == "user":
                self._user(e)
            elif t == "assistant":
                self._read_tools(e, agent_id=None)
                txt = plain_text(content_blocks(e))
                if txt:
                    self.replies.append((e.get("timestamp") or "", self._next(), txt))
            elif t == "attachment":
                self._attachment(e)

    def _user(self, e: dict) -> None:
        blocks = content_blocks(e)
        for b in blocks:
            if b.get("type") == "tool_result":
                self._tool_result(e, b)
        if e.get("isMeta") or any(b.get("type") == "tool_result" for b in blocks):
            return
        text = plain_text(blocks)
        if not text:
            return
        if self._maybe_peer(e, text):
            return
        origin = e.get("origin")
        if isinstance(origin, dict) and origin.get("kind") not in (None, "human"):
            # Harness-injected input (PR alerts, scheduled check-ins, ...): neither
            # typed by the user nor returned by a subagent.
            warn(f"system-origin input ({origin.get('kind')}) is not a turn; skipped")
            return
        self._add_turn(e, "human", text, source="user")

    def _attachment(self, e: dict) -> None:
        a = e.get("attachment")
        if not isinstance(a, dict):
            return
        if a.get("type") != "queued_command":
            return
        prompt = a.get("prompt")
        if isinstance(prompt, list):
            prompt = plain_text([b for b in prompt if isinstance(b, dict)])
        if not isinstance(prompt, str) or not prompt.strip():
            return
        text = SR_RE.sub("", prompt).strip()
        if self._maybe_peer(e, text):
            return
        self._add_turn(e, "human", text, source="queued_command")

    def _maybe_peer(self, e: dict, text: str) -> bool:
        m = AGENT_MSG_RE.search(text) or TASK_NOTE_RE.search(text)
        if not m:
            return False
        agent_id = m.group(1).strip()
        body = re.sub(r"</?agent-message[^>]*>", "", text)
        # Drop the harness framing in front of the subagent's own report.
        body = re.sub(r"^.*?The report follows:\s*", "", body, count=1, flags=re.S).strip()
        res = re.search(r"<result>(.*?)</result>", body, re.S)
        if res:  # <task-notification>: keep the result, drop the envelope
            body = res.group(1).strip()
        prev = self.peer_by_agent.get(agent_id)
        if prev and prev["source"] != "tool_result":
            warn(f"second delivery for agent {agent_id}; kept the first")
            return True
        turn = self._make_turn(e, "peer_agent", body, source="agent_message")
        turn["agent_id"] = agent_id
        if prev:  # replace the tool_result stub with the real delivery
            self.turns.remove(prev)
        self.peer_by_agent[agent_id] = turn
        self.turns.append(turn)
        return True

    def _tool_result(self, e: dict, b: dict) -> None:
        tid = b.get("tool_use_id")
        if not tid:
            return
        tur = e.get("toolUseResult")
        is_err = bool(b.get("is_error"))
        txt = result_text(b)
        self.results[tid] = {"ok": not is_err, "error": redact(txt)[:200] if is_err else None}
        agent_id = tur.get("agentId") if isinstance(tur, dict) else None
        if agent_id:
            self.agent_calls[agent_id] = tid
            if agent_id not in self.peer_by_agent:
                turn = self._make_turn(e, "peer_agent", txt.strip() or "(subagent result)",
                                       source="tool_result")
                turn["agent_id"] = agent_id
                self.peer_by_agent[agent_id] = turn
                self.turns.append(turn)

    def _read_tools(self, e: dict, agent_id: str | None) -> None:
        for b in content_blocks(e):
            bt = b.get("type")
            if bt == "tool_use":
                tid = b.get("id")
                if not tid or tid in self.calls:
                    continue
                name = b.get("name") or "unknown"
                self.calls[tid] = {
                    "id": tid, "tool_name": name, "input": b.get("input"),
                    "timestamp": e.get("timestamp") or "", "order": self._next(),
                    "agent_id": agent_id,
                }
            elif bt == "tool_result" and agent_id:
                self._tool_result(e, b)
            elif bt not in ("text", "thinking", "redacted_thinking", "tool_result",
                            "image", "document", None):
                warn(f"unknown content block {bt!r}; skipped")

    def _make_turn(self, e, role, text, source) -> dict:
        return {
            "id": e.get("uuid") or f"{self.session_id}:{self._next()}",
            "role": role, "timestamp": e.get("timestamp") or "",
            "text": text, "source": source, "order": self._next(),
        }

    def _add_turn(self, e, role, text, source) -> None:
        self.turns.append(self._make_turn(e, role, text, source))

    # ---- subagents --------------------------------------------------------
    def read_subagents(self) -> None:
        sub_dir = Path(self.session_path).with_suffix("") / "subagents"
        for path in sorted(glob.glob(str(sub_dir / "*.jsonl"))):
            stem = Path(path).stem
            agent_id = stem[len("agent-"):] if stem.startswith("agent-") else stem
            for lineno, e in read_jsonl(path):
                t = e.get("type")
                if t not in KNOWN_TYPES:
                    warn(f"{stem}: unknown entry type {t!r} (line {lineno}); skipped")
                    self.skipped[str(t)] = self.skipped.get(str(t), 0) + 1
                    continue
                if t in ("assistant", "user"):
                    self._read_tools(e, agent_id=e.get("agentId") or agent_id)

    # ---- assemble ---------------------------------------------------------
    def build(self) -> dict:
        self.read_main()
        self.read_subagents()
        turns = sorted(self.turns, key=lambda t: (t["timestamp"], t["order"]))
        # Dedupe on id (a uuid can carry both an Agent result and text).
        seen, uniq = set(), []
        for t in turns:
            if t["id"] in seen:
                t["id"] = f"{t['id']}:{t['order']}"
            seen.add(t["id"])
            uniq.append(t)
        turns = uniq
        for i, t in enumerate(turns):
            t["index"] = i
        peer_index = {t["agent_id"]: t["index"] for t in turns if t.get("agent_id")}
        times = [t["timestamp"] for t in turns]

        def turn_at(ts: str) -> int:
            idx = 0
            for i, tt in enumerate(times):
                if tt and ts and tt <= ts:
                    idx = i
            return idx

        # Assistant reply text belongs to the turn it answers.
        replies: dict[int, list[str]] = {}
        for ts, _, txt in sorted(self.replies):
            replies.setdefault(turn_at(ts), []).append(txt)
        for t in turns:
            t["reply"] = "\n\n".join(replies.get(t["index"], []))

        tool_calls, files, skills = [], {}, {}
        for c in sorted(self.calls.values(), key=lambda c: (c["timestamp"], c["order"])):
            if c["agent_id"] and c["agent_id"] in peer_index:
                ti = peer_index[c["agent_id"]]
            elif c["agent_id"] and c["agent_id"] in self.agent_calls:
                parent = self.calls.get(self.agent_calls[c["agent_id"]])
                ti = turn_at(parent["timestamp"]) if parent else turn_at(c["timestamp"])
            else:
                ti = turn_at(c["timestamp"])
            res = self.results.get(c["id"])
            call = {
                "id": c["id"], "turn_index": ti, "tool_name": c["tool_name"],
                "input_summary": summarize_input(c["tool_name"], c["input"]),
                "ok": res["ok"] if res else None,
                "error": res["error"] if res else None,
                "agent_id": c["agent_id"], "timestamp": c["timestamp"],
                "files": [], "skill": None,
            }
            for path, how in files_from_tool(c["tool_name"], c["input"]):
                f = files.setdefault(path, {"path": path, "how": how, "touches": 0})
                if how == "input":
                    f["how"] = "input"
                f["touches"] += 1
                call["files"].append(path)
            if c["tool_name"] == "Skill" and isinstance(c["input"], dict):
                name = c["input"].get("skill") or c["input"].get("name")
                if isinstance(name, str) and name:
                    skills.setdefault(name, {"name": name, "invocations": 0})["invocations"] += 1
                    call["skill"] = name
            tool_calls.append(call)

        for t in turns:
            t.pop("order", None)
        return {
            "schema": "session-graph/extract/v1",
            "session": {
                "id": self.session_id, "path": os.path.abspath(self.session_path),
                "started": times[0] if times else None,
                "ended": times[-1] if times else None, **self.meta,
            },
            "turns": turns,
            "tool_calls": tool_calls,
            "files": sorted(files.values(), key=lambda f: f["path"]),
            "skills": sorted(skills.values(), key=lambda s: s["name"]),
            "skipped_entry_types": self.skipped,
        }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("session")
    ap.add_argument("-o", "--out")
    a = ap.parse_args(argv)
    data = Extractor(a.session).build()
    out = a.out or os.path.join("out", data["session"]["id"], "extract.json")
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w") as fh:
        json.dump(data, fh, indent=1, default=str)
    n = data
    print(f"[extract] {out}: {len(n['turns'])} turns, {len(n['tool_calls'])} tool calls, "
          f"{len(n['files'])} files, {len(n['skills'])} skills", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
