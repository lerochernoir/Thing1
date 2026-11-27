"""Independent counter over the raw JSONL — written separately from extract.py
so the test compares two implementations of the README's counting rules."""
import glob
import json
import os
import re
from collections import Counter


def _rows(path):
    for line in open(path, encoding="utf-8", errors="replace"):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if isinstance(d, dict):
            yield d


def _text(content):
    if isinstance(content, str):
        s = content
    elif isinstance(content, list):
        s = "\n".join(b.get("text", "") for b in content
                      if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str))
    else:
        s = ""
    return re.sub(r"<system-reminder>.*?</system-reminder>", "", s, flags=re.S).strip()


PEER = re.compile(r'<agent-message from="([^"]+)"|<task-notification>.*?<task-id>([^<]+)</task-id>', re.S)


def count(session_path):
    stem = os.path.splitext(session_path)[0]
    sub_files = sorted(glob.glob(os.path.join(stem, "subagents", "*.jsonl")))
    human, peers = 0, set()
    tool_ids, by_tool, skills, input_files = set(), Counter(), set(), set()
    errors = set()
    for f in [session_path] + sub_files:
        main = f == session_path
        for d in _rows(f):
            msg = d.get("message") if isinstance(d.get("message"), dict) else {}
            content = msg.get("content")
            blocks = content if isinstance(content, list) else []
            for b in blocks:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "tool_use" and b.get("id") and b["id"] not in tool_ids:
                    tool_ids.add(b["id"])
                    by_tool[b.get("name")] += 1
                    inp = b.get("input") or {}
                    if b.get("name") == "Skill" and inp.get("skill"):
                        skills.add(inp["skill"])
                    for k in ("file_path", "notebook_path"):
                        if b.get("name") in ("Read", "Write", "Edit", "MultiEdit", "NotebookEdit") and inp.get(k):
                            input_files.add(inp[k])
                if b.get("type") == "tool_result" and b.get("is_error"):
                    errors.add(b.get("tool_use_id"))
            if not main or d.get("isSidechain"):
                continue
            tur = d.get("toolUseResult")
            if d.get("type") == "user" and isinstance(tur, dict) and tur.get("agentId"):
                peers.add(tur["agentId"])
            if d.get("type") == "user" and not d.get("isMeta") \
                    and not any(isinstance(b, dict) and b.get("type") == "tool_result" for b in blocks):
                t = _text(content)
                kind = (d.get("origin") or {}).get("kind") if isinstance(d.get("origin"), dict) else None
                if t:
                    m = PEER.search(t)
                    if m:
                        peers.add(m.group(1) or m.group(2).strip())
                    elif kind in (None, "human"):
                        human += 1
            if d.get("type") == "attachment" and isinstance(d.get("attachment"), dict) \
                    and d["attachment"].get("type") == "queued_command":
                p = d["attachment"].get("prompt")
                t = _text(p) if p is not None else ""
                if t:
                    m = PEER.search(t)
                    if m:
                        peers.add(m.group(1) or m.group(2).strip())
                    else:
                        human += 1
    return {
        "human_turns": human, "peer_turns": len(peers), "turns": human + len(peers),
        "tool_calls": len(tool_ids), "by_tool": dict(by_tool), "skills": len(skills),
        "input_files": input_files, "errors": len(errors & tool_ids),
    }
