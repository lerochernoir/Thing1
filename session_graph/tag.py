#!/usr/bin/env python3
"""Step 4 — tag (layer 2, semantic, model-generated).

    python3 tag.py out/<uuid>/extract.json [-o out/<uuid>/tagged.json] [--batch-size 12]

Sends turn texts (the incoming human / peer-agent text plus Claude's reply
to it) to Claude in batches and asks for topics, decisions and questions
under a strict JSON schema. This is the ONLY step that sends transcript
text off the machine. Before sending:
  * every string goes through redact.redact() (API keys, tokens, private
    keys, assigned secrets, URL credentials, email addresses);
  * tool inputs, tool results and file contents are never sent;
  * --dry-run writes the exact redacted payload to disk and sends nothing.

Batches run in order; each batch sees the decisions and questions found so
far (by final id) so it can mark SUPERSEDES / DEFERS links and resolve
earlier questions. Ids are assigned by this script, not the model:
decisions D0..Dn and questions Q1..Qn in turn order.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

from redact import redact

MODEL = "claude-opus-5-5"
MAX_CHARS_PER_TURN = 6000

DECISION_STATUS = ["accepted", "accepted_by_default", "rejected", "deferred"]
QUESTION_STATUS = ["open", "resolved"]

NULL_INT = {"anyOf": [{"type": "integer"}, {"type": "null"}]}
NULL_STR = {"anyOf": [{"type": "string"}, {"type": "null"}]}


def _obj(props: dict) -> dict:
    return {"type": "object", "properties": props,
            "required": list(props), "additionalProperties": False}


OUTPUT_SCHEMA = _obj({
    "topics": {"type": "array", "items": _obj({
        "slug": {"type": "string"},
        "turn_indexes": {"type": "array", "items": {"type": "integer"}},
        "confidence": {"type": "number"},
    })},
    "decisions": {"type": "array", "items": _obj({
        "ref": {"type": "string"},
        "text": {"type": "string"},
        "status": {"type": "string", "enum": DECISION_STATUS},
        "turn_index": {"type": "integer"},
        "supersedes": NULL_STR,
        "defers": NULL_STR,
        "topics": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number"},
    })},
    "questions": {"type": "array", "items": _obj({
        "ref": {"type": "string"},
        "text": {"type": "string"},
        "status": {"type": "string", "enum": QUESTION_STATUS},
        "raised_in": {"type": "integer"},
        "resolved_in": NULL_INT,
        "confidence": {"type": "number"},
    })},
    "resolutions": {"type": "array", "items": _obj({
        "question_id": {"type": "string"},
        "resolved_in": {"type": "integer"},
        "confidence": {"type": "number"},
    })},
})

SYSTEM = """You annotate one Claude Code session for a knowledge graph.
You receive numbered turns. Each turn is the text that came INTO the conversation
(role "human" = the user typed it; role "peer_agent" = a subagent's result coming
back) followed by Claude's reply to it. Return only what the text supports.

topics: short kebab-case slugs (2-4 words, e.g. "graph-layout", "secret-redaction")
  for subjects that recur or matter; list every turn index where each appears.
decisions: choices actually made about the work. status:
  accepted            = explicitly chosen or agreed
  accepted_by_default = adopted without anyone deciding out loud (a default,
                        an assumption acted on, a fallback taken)
  rejected            = considered and turned down
  deferred            = explicitly postponed
  turn_index = the turn where it was made. supersedes / defers = the id of an
  earlier decision this one replaces or postpones (a "D" id from the prior list,
  or the ref of a decision in this batch), else null. topics = slugs it concerns.
questions: open issues raised. status "resolved" only if a later turn in this batch
  answers it (resolved_in = that turn), else "open" with resolved_in null.
resolutions: earlier open questions (by "Q" id from the prior list) that a turn in
  this batch resolves.
refs: any unique string within this batch (e.g. "d1", "q1"); final ids are
  assigned later.
confidence: 0..1, your confidence the item is real and correctly typed.
Text marked [REDACTED:...] was removed for privacy; do not guess it."""


def slugify(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s[:48] or "untitled"


def clamp(x) -> float:
    try:
        return max(0.0, min(1.0, float(x)))
    except (TypeError, ValueError):
        return 0.5


def turn_payload(t: dict) -> dict:
    return {
        "index": t["index"], "role": t["role"],
        "text": redact(t["text"])[:MAX_CHARS_PER_TURN],
        "claude_reply": redact(t.get("reply") or "")[:MAX_CHARS_PER_TURN],
    }


def batch_prompt(batch: list[dict], state: dict) -> str:
    prior_d = [{"id": d["id"], "text": d["text"], "status": d["status"]} for d in state["decisions"]]
    prior_q = [{"id": q["id"], "text": q["text"]} for q in state["questions"] if q["status"] == "open"]
    return json.dumps({
        "prior_decisions": prior_d,
        "prior_open_questions": prior_q,
        "known_topics": sorted(state["topics"]),
        "turns": [turn_payload(t) for t in batch],
    }, ensure_ascii=False, indent=1)


def call_claude(client, prompt: str, use_fallback: bool) -> dict:
    kwargs = dict(
        model=MODEL, max_tokens=16000, system=SYSTEM,
        output_config={"effort": "medium",
                       "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
        messages=[{"role": "user", "content": prompt}],
    )
    if use_fallback:
        # Server-side refusal fallback: a declined batch is re-run on a fallback model.
        resp = client.beta.messages.create(
            betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
    else:
        resp = client.messages.create(**kwargs)
    if resp.stop_reason == "refusal":
        raise RuntimeError(f"model refused batch: {getattr(resp, 'stop_details', None)}")
    if resp.stop_reason == "max_tokens":
        raise RuntimeError("batch output hit max_tokens; lower --batch-size")
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text)


def merge_batch(out: dict, batch: list[dict], state: dict) -> None:
    valid = {t["index"] for t in batch}
    for t in out.get("topics", []):
        slug = slugify(t["slug"])
        idx = sorted(i for i in t.get("turn_indexes", []) if i in valid)
        if not idx:
            continue
        cur = state["topics"].setdefault(slug, {"slug": slug, "turn_indexes": [], "confidence": 0.0})
        cur["turn_indexes"] = sorted(set(cur["turn_indexes"]) | set(idx))
        cur["confidence"] = max(cur["confidence"], clamp(t.get("confidence")))

    refmap: dict[str, str] = {}
    new_decisions = sorted((d for d in out.get("decisions", []) if d.get("turn_index") in valid),
                           key=lambda d: d["turn_index"])
    for d in new_decisions:
        refmap[d["ref"]] = f"D{len(state['decisions'])}"
        state["decisions"].append({
            "id": refmap[d["ref"]], "text": d["text"].strip(), "status": d["status"],
            "turn_index": d["turn_index"], "confidence": clamp(d.get("confidence")),
            "topics": sorted({slugify(s) for s in d.get("topics", [])}),
            "_supersedes": d.get("supersedes"), "_defers": d.get("defers"),
        })
    known = {d["id"] for d in state["decisions"]}
    for d in state["decisions"]:
        for k in ("supersedes", "defers"):
            raw = d.pop(f"_{k}", None) if f"_{k}" in d else d.get(k)
            target = refmap.get(raw, raw) if raw else None
            d[k] = target if target in known and target != d["id"] else None

    qmap: dict[str, str] = {}
    for q in sorted((q for q in out.get("questions", []) if q.get("raised_in") in valid),
                    key=lambda q: q["raised_in"]):
        qmap[q["ref"]] = f"Q{len(state['questions']) + 1}"
        res = q.get("resolved_in")
        res = res if (q["status"] == "resolved" and res in valid and res >= q["raised_in"]) else None
        state["questions"].append({
            "id": qmap[q["ref"]], "text": q["text"].strip(),
            "status": "resolved" if res is not None else "open",
            "raised_in": q["raised_in"], "resolved_in": res, "confidence": clamp(q.get("confidence")),
        })
    by_id = {q["id"]: q for q in state["questions"]}
    for r in out.get("resolutions", []):
        q = by_id.get(r.get("question_id"))
        if q and q["status"] == "open" and r.get("resolved_in") in valid \
                and r["resolved_in"] >= q["raised_in"]:
            q["status"], q["resolved_in"] = "resolved", r["resolved_in"]

    # Topics referenced by decisions must exist as Topic nodes.
    for d in state["decisions"]:
        for slug in d["topics"]:
            cur = state["topics"].setdefault(slug, {"slug": slug, "turn_indexes": [], "confidence": d["confidence"]})
            if d["turn_index"] not in cur["turn_indexes"]:
                cur["turn_indexes"] = sorted(set(cur["turn_indexes"]) | {d["turn_index"]})


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("extract")
    ap.add_argument("-o", "--out")
    ap.add_argument("--batch-size", type=int, default=12)
    ap.add_argument("--dry-run", action="store_true",
                    help="write the redacted payloads to <out>.payload.json; send nothing")
    ap.add_argument("--no-fallback", action="store_true",
                    help="do not send the server-side refusal-fallback parameter")
    a = ap.parse_args(argv)

    data = json.load(open(a.extract))
    sid = data["session"]["id"]
    out_path = a.out or os.path.join(os.path.dirname(a.extract), "tagged.json")
    turns = data["turns"]
    batches = [turns[i:i + a.batch_size] for i in range(0, len(turns), a.batch_size)]
    state = {"topics": {}, "decisions": [], "questions": []}

    if a.dry_run:
        payload = [{"system": SYSTEM, "user": batch_prompt(b, state)} for b in batches]
        with open(out_path + ".payload.json", "w") as fh:
            json.dump(payload, fh, indent=1, ensure_ascii=False)
        print(f"[tag] dry run: {len(batches)} batch(es) written to {out_path}.payload.json", file=sys.stderr)
        return 0

    try:
        import anthropic
    except ImportError:
        print("[tag] the anthropic package is not installed (pip install -r requirements.txt)", file=sys.stderr)
        return 3
    client = anthropic.Anthropic()
    for n, b in enumerate(batches, 1):
        print(f"[tag] batch {n}/{len(batches)}: turns {b[0]['index']}..{b[-1]['index']}", file=sys.stderr)
        try:
            out = call_claude(client, batch_prompt(b, state), use_fallback=not a.no_fallback)
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as e:
            print(f"[tag] Claude API rejected the credentials: {e}", file=sys.stderr)
            return 3
        except TypeError as e:
            if "authentication" not in str(e).lower():
                raise
            # The SDK raises TypeError before sending when no credential resolves.
            print("[tag] no Claude API credentials (set ANTHROPIC_API_KEY or run `ant auth login`)",
                  file=sys.stderr)
            return 3
        except anthropic.APIConnectionError as e:
            print(f"[tag] could not reach the Claude API: {e}", file=sys.stderr)
            return 4
        merge_batch(out, b, state)

    tagged = {
        "schema": "session-graph/tagged/v1", "session_id": sid, "model": MODEL,
        "topics": sorted(state["topics"].values(), key=lambda t: t["slug"]),
        "decisions": state["decisions"], "questions": state["questions"],
    }
    with open(out_path, "w") as fh:
        json.dump(tagged, fh, indent=1, ensure_ascii=False)
    print(f"[tag] {out_path}: {len(tagged['topics'])} topics, {len(tagged['decisions'])} decisions, "
          f"{len(tagged['questions'])} questions", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
