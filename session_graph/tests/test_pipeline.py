"""End-to-end checks: graph counts in Relate must equal counts taken from the raw log.

    pytest tests/                                  # synthetic drift fixture
    SESSION_JSONL=~/.claude/projects/<slug>/<uuid>.jsonl pytest tests/   # + one real session
"""
import json
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import extract  # noqa: E402
import run_cypher  # noqa: E402
import tag  # noqa: E402
from raw_counts import count  # noqa: E402
from redact import redact  # noqa: E402

SYNTH = os.path.join(HERE, "fixtures", "synthetic", "5e55a0e0-0000-4000-8000-00000000f107.jsonl")
SYNTH_TAGGED = os.path.join(HERE, "fixtures", "synthetic.tagged.json")


def build(session, tmp, tagged=None):
    data = extract.Extractor(session).build()
    db = str(tmp / "graph.rl")
    stmts = lambda f: run_cypher.split_statements(open(os.path.join(ROOT, f)).read())  # noqa: E731
    run_cypher.run(db, stmts("schema.cypher"), {})
    params = run_cypher.params_for(json.loads(json.dumps(data, default=str)))
    run_cypher.run(db, stmts("load.cypher"), params)
    if tagged:
        run_cypher.run(db, stmts("layer2.cypher"), run_cypher.params_for(json.load(open(tagged))))
    return data, db


def q(db, cypher, **p):
    return run_cypher.run(db, [cypher], p)[0]


def graph_counts(db, sid):
    one = lambda c: q(db, c, sid=sid)[0]["n"]  # noqa: E731
    return {
        "turns": one("MATCH (:Session {id:$sid})-[:HAS_TURN]->(t:Turn) RETURN count(t) AS n"),
        "human_turns": one("MATCH (t:Turn {session_id:$sid, role:'human'}) RETURN count(t) AS n"),
        "peer_turns": one("MATCH (t:Turn {session_id:$sid, role:'peer_agent'}) RETURN count(t) AS n"),
        "tool_calls": one("MATCH (:Turn {session_id:$sid})-[:MADE]->(c:ToolCall) RETURN count(c) AS n"),
        "skills": one("MATCH (:Turn {session_id:$sid})-[:MADE]->()-[:INVOKED]->(k:Skill) RETURN count(DISTINCT k) AS n"),
        "errors": one("MATCH (c:ToolCall {session_id:$sid}) WHERE c.ok = false RETURN count(c) AS n"),
        "next": one("MATCH (a:Turn {session_id:$sid})-[:NEXT]->(:Turn) RETURN count(a) AS n"),
        "by_tool": {r["t"]: r["n"] for r in q(db, "MATCH (:Turn {session_id:$sid})-[:MADE]->(:ToolCall)-[:USED]->(t:Tool) RETURN t.name AS t, count(*) AS n", sid=sid)},
        "files": {r["p"] for r in q(db, "MATCH (:Turn {session_id:$sid})-[:MADE]->()-[:TOUCHED]->(f:File) RETURN DISTINCT f.path AS p", sid=sid)},
    }


def assert_matches_raw(session, db, data):
    raw = count(session)
    g = graph_counts(db, data["session"]["id"])
    for k in ("turns", "human_turns", "peer_turns", "tool_calls", "skills", "errors", "by_tool"):
        assert g[k] == raw[k], f"{k}: graph {g[k]} != raw {raw[k]}"
    assert g["next"] == max(raw["turns"] - 1, 0)
    assert raw["input_files"] <= g["files"], raw["input_files"] - g["files"]
    assert len(g["files"]) == len(data["files"])
    return raw, g


def test_synthetic_counts_match_raw(tmp_path):
    data, db = build(SYNTH, tmp_path, SYNTH_TAGGED)
    raw, g = assert_matches_raw(SYNTH, db, data)
    assert (raw["human_turns"], raw["peer_turns"], raw["tool_calls"]) == (9, 2, 18)


def test_drift_is_logged_not_raised(capsys):
    extract.Extractor(SYNTH).build()
    err = capsys.readouterr().err
    assert "unknown entry type 'mystery-telemetry'" in err
    assert "unknown content block 'hologram'" in err
    assert "bad JSON" in err and "non-object line" in err


def test_load_is_idempotent(tmp_path):
    data, db = build(SYNTH, tmp_path, SYNTH_TAGGED)
    before = q(db, "MATCH (n) RETURN count(n) AS n")[0]["n"], q(db, "MATCH ()-[r]->() RETURN count(r) AS n")[0]["n"]
    params = run_cypher.params_for(json.loads(json.dumps(data, default=str)))
    for f, p in (("load.cypher", params), ("layer2.cypher", run_cypher.params_for(json.load(open(SYNTH_TAGGED))))):
        run_cypher.run(db, run_cypher.split_statements(open(os.path.join(ROOT, f)).read()), p)
    after = q(db, "MATCH (n) RETURN count(n) AS n")[0]["n"], q(db, "MATCH ()-[r]->() RETURN count(r) AS n")[0]["n"]
    assert before == after


def test_layer2_kept_separate(tmp_path):
    _, db = build(SYNTH, tmp_path, SYNTH_TAGGED)
    bad = q(db, "MATCH (n) WHERE (n:Topic OR n:Decision OR n:Question) AND (n.source <> 'model' OR n.confidence IS NULL) RETURN count(n) AS n")
    assert bad[0]["n"] == 0
    leaked = q(db, "MATCH (n) WHERE (n:Turn OR n:ToolCall OR n:File OR n:Tool) AND n.source IS NOT NULL RETURN count(n) AS n")
    assert leaked[0]["n"] == 0
    chain = q(db, "MATCH p = (d:Decision {id:'D7'})-[:SUPERSEDES*1..]->(old) RETURN [x IN nodes(p) | x.id] AS ids")
    assert chain[0]["ids"] == ["D7", "D0"]


def test_tag_merge_assigns_ids_and_links():
    batch = [{"index": i, "role": "human", "text": "t", "reply": ""} for i in range(3)]
    state = {"topics": {}, "decisions": [], "questions": []}
    tag.merge_batch({
        "topics": [{"slug": "Graph Layout!", "turn_indexes": [0, 2, 99], "confidence": 1.4}],
        "decisions": [
            {"ref": "b", "text": "ring", "status": "accepted", "turn_index": 2, "supersedes": "a", "defers": None, "topics": ["graph layout"], "confidence": 0.9},
            {"ref": "a", "text": "grid", "status": "accepted_by_default", "turn_index": 0, "supersedes": None, "defers": None, "topics": [], "confidence": 0.5},
        ],
        "questions": [{"ref": "q", "text": "colors?", "status": "resolved", "raised_in": 1, "resolved_in": 0, "confidence": 0.7}],
        "resolutions": [],
    }, batch, state)
    assert [(d["id"], d["text"], d["supersedes"]) for d in state["decisions"]] == [("D0", "grid", None), ("D1", "ring", "D0")]
    assert state["topics"]["graph-layout"]["turn_indexes"] == [0, 2]
    assert state["topics"]["graph-layout"]["confidence"] == 1.0
    assert state["questions"][0]["id"] == "Q1" and state["questions"][0]["status"] == "open"  # resolved_in < raised_in rejected


def test_redaction():
    s = redact("key sk-ant-api03-abcdefghijklmnop and ghp_" + "a" * 36 + " PASSWORD=hunter2hunter me@example.com")
    assert "sk-ant" not in s and "ghp_" not in s and "hunter2" not in s and "example.com" not in s


def test_tag_dry_run_sends_nothing(tmp_path):
    data = extract.Extractor(SYNTH).build()
    p = tmp_path / "extract.json"
    p.write_text(json.dumps(data, default=str))
    assert tag.main([str(p), "--dry-run", "-o", str(tmp_path / "tagged.json")]) == 0
    assert (tmp_path / "tagged.json.payload.json").exists() and not (tmp_path / "tagged.json").exists()


def test_render_produces_svg_and_png(tmp_path):
    data, db = build(SYNTH, tmp_path, SYNTH_TAGGED)
    sid = data["session"]["id"]
    subprocess.run([sys.executable, os.path.join(ROOT, "query.py"), "--db", db, "--session", sid,
                    "-o", str(tmp_path / "g.json")], check=True)
    subprocess.run(["node", os.path.join(ROOT, "render", "render.mjs"), str(tmp_path / "g.json"),
                    str(tmp_path / "g.svg"), str(tmp_path / "g.png")], check=True)
    svg = (tmp_path / "g.svg").read_text()
    assert "One chat, as a graph" in svg and "Built with Relate + Claude Code" in svg
    assert "11 turns · 18 tool calls · 6 topics · 8 decisions · 3 questions" in svg
    assert (tmp_path / "g.png").read_bytes()[:4] == b"\x89PNG"


@pytest.mark.skipif(not os.environ.get("SESSION_JSONL"), reason="set SESSION_JSONL to test a real session")
def test_real_session_counts_match_raw(tmp_path):
    session = os.path.expanduser(os.environ["SESSION_JSONL"])
    data, db = build(session, tmp_path)
    raw, g = assert_matches_raw(session, db, data)
    print(f"\nreal session {data['session']['id']}: raw={ {k: raw[k] for k in ('human_turns', 'peer_turns', 'tool_calls', 'skills', 'errors')} } "
          f"graph files={len(g['files'])}")
