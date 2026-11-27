#!/usr/bin/env python3
"""Run a .cypher file against a Relate store, binding parameters from a JSON file.

    python3 run_cypher.py --db out/<uuid>/graph.rl schema.cypher
    python3 run_cypher.py --db out/<uuid>/graph.rl load.cypher --params out/<uuid>/extract.json
    python3 run_cypher.py --db out/<uuid>/graph.rl layer2.cypher --params out/<uuid>/tagged.json
    python3 run_cypher.py --db out/<uuid>/graph.rl -e "MATCH (n) RETURN labels(n)[0] AS l, count(*) AS c"

The store is opened with the embedded engine (pip: relate-db, `import relate`),
which is the same engine the `relate` CLI runs. Statements are separated by a
`;` at the end of a line; `//` comment lines are ignored. The whole file runs
in one transaction: it either applies completely or not at all.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import relate

RELATE_VERSION = "1.3.0"  # keep in sync with requirements.txt


def split_statements(text: str) -> list[str]:
    lines = [l for l in text.splitlines() if not l.strip().startswith("//")]
    stmts, cur = [], []
    for line in lines:
        cur.append(line)
        if line.rstrip().endswith(";"):
            s = "\n".join(cur).strip().rstrip(";").strip()
            if s:
                stmts.append(s)
            cur = []
    tail = "\n".join(cur).strip()
    if tail:
        stmts.append(tail)
    return stmts


def params_for(data: dict) -> dict:
    """Flatten extract.json / tagged.json into Cypher parameters."""
    if data.get("schema", "").startswith("session-graph/extract"):
        return {k: data[k] for k in ("session", "turns", "tool_calls", "files", "skills")}
    if data.get("schema", "").startswith("session-graph/tagged"):
        return {k: data[k] for k in ("session_id", "model", "topics", "decisions", "questions")}
    return data


def connect(db_path: str, read_only: bool = False):
    if relate.__version__ != RELATE_VERSION:
        print(f"[run_cypher] warning: relate {relate.__version__} installed, "
              f"pipeline pinned to {RELATE_VERSION}", file=sys.stderr)
    if not read_only:
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    return relate.connect(db_path, read_only=read_only) if read_only else relate.connect(db_path)


def run(db_path: str, statements: list[str], params: dict, quiet=False) -> list[list[dict]]:
    conn = connect(db_path)
    out = []
    try:
        conn.autocommit = False
        for s in statements:
            used = {k: v for k, v in params.items() if f"${k}" in s}
            rows = [dict(r) for r in conn.execute(s, used)]
            out.append(rows)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--db", required=True)
    ap.add_argument("file", nargs="?")
    ap.add_argument("-e", "--execute", help="run one statement instead of a file")
    ap.add_argument("--params", help="JSON file whose contents become $parameters")
    a = ap.parse_args(argv)
    if not (a.file or a.execute):
        ap.error("give a .cypher file or -e STATEMENT")
    text = a.execute if a.execute else open(a.file).read()
    params = params_for(json.load(open(a.params))) if a.params else {}
    results = run(a.db, split_statements(text), params)
    if a.execute:
        print(json.dumps(results[-1], indent=1, default=str))
    else:
        print(f"[run_cypher] {a.file}: {len(results)} statements applied to {a.db}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
