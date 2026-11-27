#!/usr/bin/env python3
"""Generate the synthetic session used by the tests (and the README demo image).

It mimics the current Claude Code JSONL shape and deliberately includes drift:
an unknown entry type, an unknown content block, a malformed line, a
sidechain-free subagent file, a queued human prompt, a <task-notification>
peer result, an <agent-message> peer result, a Skill call and failed calls.

    python3 tests/make_fixture.py   # writes tests/fixtures/synthetic/
"""
import json
import os
import uuid
from datetime import datetime, timedelta, timezone

SID = "5e55a0e0-0000-4000-8000-00000000f1x7".replace("x", "0")
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "fixtures", "synthetic")
T0 = datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc)
_t = [0]
_n = [0]


def ts():
    _t[0] += 17
    return (T0 + timedelta(seconds=_t[0])).isoformat().replace("+00:00", "Z")


def uid():
    _n[0] += 1
    return str(uuid.UUID(int=_n[0]))


def tid():
    _n[0] += 1
    return f"toolu_{_n[0]:024d}"


main, subs = [], {}


def human(text, blocks=False):
    content = [{"type": "text", "text": text},
               {"type": "text", "text": "<system-reminder>noise</system-reminder>"}] if blocks else text
    main.append({"type": "user", "uuid": uid(), "timestamp": ts(), "sessionId": SID,
                 "userType": "external", "origin": {"kind": "human"},
                 "message": {"role": "user", "content": content}})


def say(text):
    main.append({"type": "assistant", "uuid": uid(), "timestamp": ts(),
                 "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}})


def call(name, inp, ok=True, result="ok", tur=None, into=None, agent=None):
    i = tid()
    rows = into if into is not None else main
    a = {"type": "assistant", "uuid": uid(), "timestamp": ts(),
         "message": {"role": "assistant", "content": [{"type": "tool_use", "id": i, "name": name, "input": inp}]}}
    r = {"type": "user", "uuid": uid(), "timestamp": ts(),
         "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": i,
                                                  "content": result, "is_error": not ok}]}}
    if tur is not None:
        r["toolUseResult"] = tur
    if agent:
        a["agentId"] = r["agentId"] = agent
    rows += [a, r]
    return i


def subagent(agent_id, prompt, calls):
    rows = subs.setdefault(agent_id, [])
    rows.append({"type": "user", "uuid": uid(), "timestamp": ts(), "agentId": agent_id,
                 "message": {"role": "user", "content": prompt}})
    for name, inp in calls:
        call(name, inp, into=rows, agent=agent_id)


main.append({"type": "ai-title", "aiTitle": "Radial graph for a coding session", "sessionId": SID})
human("Build a CLI that turns a chat log into a graph. Store it in a local graph DB. Should we use SQLite or a graph DB?")
say("A graph DB fits better. I'll start with the embedded one and keep SQLite out.")
call("Bash", {"command": "cd /work/app && ls src docs/plan.md", "description": "List project files"})
call("Read", {"file_path": "/work/app/README.md"})
human("Use Relate, pin the version. What's the license of the CLI binary?", blocks=True)
say("Pinned relate-db 1.3.0. License question stays open for now.")
call("Write", {"file_path": "/work/app/requirements.txt", "content": "relate-db==1.3.0\n"})
call("Bash", {"command": "pip install -r /work/app/requirements.txt", "description": "Install deps"})
main.append({"type": "mystery-telemetry", "payload": {"x": 1}})          # unknown entry type
main.append({"type": "assistant", "uuid": uid(), "timestamp": ts(),
             "message": {"role": "assistant", "content": [{"type": "hologram", "data": "?"}]}})  # unknown block
human("Layout: radial, turns on a ring. Decide colors later.")
say("Ring layout accepted; color palette deferred.")
call("Edit", {"file_path": "/work/app/render.mjs", "old_string": "a", "new_string": "b"})
call("Bash", {"command": "node /work/app/render.mjs out/graph.json", "description": "Render once"},
     ok=False, result="Error: Cannot find module 'd3'")
call("Bash", {"command": "cd /work/app && npm install d3@7.9.0", "description": "Install d3"})
human("Research how other tools draw transcripts.")
a1 = call("Agent", {"description": "Survey transcript viz", "prompt": "Survey...", "subagent_type": "general-purpose"},
          result="Report delivered as a message.", tur={"status": "completed", "agentId": "a1aaaaaaaaaaaaaaa"})
subagent("a1aaaaaaaaaaaaaaa", "Survey transcript visualisations", [
    ("WebSearch", {"query": "conversation graph visualisation radial"}),
    ("Read", {"file_path": "/work/app/docs/plan.md"}),
])
main.append({"type": "attachment", "uuid": uid(), "timestamp": ts(),
             "attachment": {"type": "queued_command", "prompt":
                            '<agent-message from="a1aaaaaaaaaaaaaaa">\n[Subagent hand-back] framing. The report follows:\n'
                            "  Most tools use timelines; radial layouts are rare. Recommend the ring.\n</agent-message>"}})
say("The survey backs the ring layout.")
main.append({"type": "attachment", "uuid": uid(), "timestamp": ts(),
             "attachment": {"type": "queued_command", "prompt": "Also add a PNG export."}})   # queued human prompt
call("Bash", {"command": "cd /work/app && npm install @resvg/resvg-js@2.6.2", "description": "Install resvg"})
human("Use the docs skill to write the README.")
call("Skill", {"skill": "docs", "args": "README for the graph CLI"})
call("Write", {"file_path": "/work/app/README.md", "content": "# graph cli\n"})
main.append("not an object")                                              # malformed shape
human("Run a background agent to load the second session.")
call("Agent", {"description": "Load session two", "prompt": "Load...", "run_in_background": True},
     result="Started in background.", tur={"status": "async_launched", "agentId": "b2bbbbbbbbbbbbbbb"})
subagent("b2bbbbbbbbbbbbbbb", "Load session two", [
    ("Bash", {"command": "python3 /work/app/load.py /data/s2.jsonl", "description": "Load s2"}),
])
human("<task-notification>\n<task-id>b2bbbbbbbbbbbbbbb</task-id>\n<status>completed</status>\n<result>Loaded 41 turns.</result>\n</task-notification>")
say("Session two loaded. Switching the store from a directory to a single .rl file instead.")
call("Edit", {"file_path": "/work/app/load.py", "old_string": "dir", "new_string": "file.rl"})
human("Actually drop SQLite export entirely. Is resvg font handling OK on Linux?")
say("Dropped the SQLite export. Font handling: resvg loads system fonts; verified with DejaVu.")
call("Skill", {"skill": "docs", "args": "update README"})
call("Read", {"file_path": "/work/app/README.md"})
main.append({"type": "user", "isMeta": True, "uuid": uid(), "timestamp": ts(),
             "message": {"role": "user", "content": "<command-name>/clear</command-name>"}})
main.append({"type": "user", "uuid": uid(), "timestamp": ts(), "origin": {"kind": "task-notification"},
             "message": {"role": "user", "content": "<task-notification>\n<task-type>queued-remote-notifications</task-type>\n<status>pending</status>\n</task-notification>"}})  # system alert: not a turn
human("Ship it.")
say("Done.")

os.makedirs(os.path.join(OUT, SID, "subagents"), exist_ok=True)
with open(os.path.join(OUT, f"{SID}.jsonl"), "w") as fh:
    for row in main:
        fh.write(json.dumps(row) + "\n")
    fh.write("{this line is broken json\n")
for aid, rows in subs.items():
    with open(os.path.join(OUT, SID, "subagents", f"agent-{aid}.jsonl"), "w") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
print(os.path.join(OUT, f"{SID}.jsonl"))
