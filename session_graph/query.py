#!/usr/bin/env python3
"""Step 6a — read one session's graph back out of Relate for the renderer.

    python3 query.py --db out/<uuid>/graph.rl --session <uuid> -o out/<uuid>/graph.json

Everything the picture shows comes from these Cypher queries, not from the
intermediate JSON files, so the render always reflects what is in the store.
"""
from __future__ import annotations

import argparse
import json
import sys

import relate

Q = {
    "session": "MATCH (s:Session {id: $sid}) RETURN s.id AS id, s.title AS title, s.started AS started",
    "turns": """MATCH (:Session {id: $sid})-[:HAS_TURN]->(t:Turn)
                RETURN t.id AS id, t.index AS index, t.role AS role ORDER BY t.index""",
    "tool_calls": """MATCH (t:Turn {session_id: $sid})-[:MADE]->(c:ToolCall)-[:USED]->(tool:Tool)
                     RETURN c.id AS id, t.index AS turn_index, tool.name AS tool, c.ok AS ok
                     ORDER BY c.timestamp, c.id""",
    "tools": """MATCH (t:Turn {session_id: $sid})-[:MADE]->(:ToolCall)-[:USED]->(tool:Tool)
                RETURN tool.name AS name, count(*) AS calls ORDER BY calls DESC, name""",
    "files": """MATCH (t:Turn {session_id: $sid})-[:MADE]->(c:ToolCall)-[:TOUCHED]->(f:File)
                RETURN f.path AS path, count(c) AS touches, collect(c.id) AS calls
                ORDER BY touches DESC, path""",
    "skills": """MATCH (t:Turn {session_id: $sid})-[:MADE]->(c:ToolCall)-[:INVOKED]->(k:Skill)
                 RETURN k.name AS name, count(c) AS calls, collect(c.id) AS call_ids ORDER BY name""",
    "topics": """MATCH (t:Turn {session_id: $sid})-[r:DISCUSSES]->(tp:Topic)
                 RETURN tp.slug AS slug, collect(t.index) AS turn_indexes,
                        max(r.confidence) AS confidence ORDER BY slug""",
    "decisions": """MATCH (d:Decision {session_id: $sid})-[:DECIDED_IN]->(t:Turn)
                    RETURN d.id AS id, d.text AS text, d.status AS status, t.index AS turn_index,
                           d.confidence AS confidence ORDER BY t.index, d.id""",
    "supersedes": """MATCH (a:Decision {session_id: $sid})-[:SUPERSEDES]->(b:Decision)
                     RETURN a.id AS src, b.id AS dst""",
    "defers": """MATCH (a:Decision {session_id: $sid})-[:DEFERS]->(b:Decision)
                 RETURN a.id AS src, b.id AS dst""",
    "questions": """MATCH (q:Question {session_id: $sid})-[:RAISED_IN]->(t:Turn)
                    OPTIONAL MATCH (q)-[:RESOLVED_IN]->(r:Turn)
                    RETURN q.id AS id, q.text AS text, q.status AS status,
                           t.index AS raised_in, r.index AS resolved_in ORDER BY t.index, q.id""",
}


def export(db_path: str, sid: str) -> dict:
    conn = relate.connect(db_path, read_only=True)
    try:
        out = {k: [dict(r) for r in conn.execute(q, {"sid": sid})] for k, q in Q.items()}
    finally:
        conn.close()
    out["session"] = out["session"][0] if out["session"] else {"id": sid}
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--db", required=True)
    ap.add_argument("--session", required=True)
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args(argv)
    g = export(a.db, a.session)
    with open(a.out, "w") as fh:
        json.dump(g, fh, indent=1, default=str)
    print(f"[query] {a.out}: {len(g['turns'])} turns, {len(g['tool_calls'])} tool calls, "
          f"{len(g['topics'])} topics, {len(g['decisions'])} decisions, "
          f"{len(g['questions'])} questions", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
