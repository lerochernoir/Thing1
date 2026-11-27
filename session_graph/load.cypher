// Step 3 — layer 1 (episodic, deterministic). Idempotent: every write is a MERGE.
// Parameters come from extract.json: $session, $turns, $tool_calls, $files, $skills.
//   (:Session)-[:HAS_TURN]->(:Turn)-[:NEXT]->(:Turn)
//   (:Turn)-[:MADE]->(:ToolCall)-[:USED]->(:Tool)
//   (:ToolCall)-[:TOUCHED]->(:File)
//   (:ToolCall)-[:INVOKED]->(:Skill)

MERGE (s:Session {id: $session.id})
SET s.path = $session.path, s.title = $session.title, s.cwd = $session.cwd,
    s.git_branch = $session.gitBranch, s.cc_version = $session.version,
    s.started = $session.started, s.ended = $session.ended, s.layer = 1;

UNWIND $turns AS t
MATCH (s:Session {id: $session.id})
MERGE (n:Turn {id: t.id})
SET n.session_id = $session.id, n.index = t.index, n.role = t.role,
    n.timestamp = t.timestamp, n.text = left(t.text, 4000), n.reply = left(t.reply, 4000),
    n.delivery = t.source, n.agent_id = t.agent_id, n.layer = 1
MERGE (s)-[:HAS_TURN]->(n);

MATCH (n:Turn {session_id: $session.id})
WITH n ORDER BY n.index
WITH collect(n) AS ts
UNWIND range(0, size(ts) - 2) AS i
WITH ts[i] AS a, ts[i + 1] AS b
MERGE (a)-[:NEXT]->(b);

UNWIND $tool_calls AS c
MATCH (t:Turn {session_id: $session.id, index: c.turn_index})
MERGE (tc:ToolCall {id: c.id})
SET tc.session_id = $session.id, tc.turn_index = c.turn_index, tc.tool_name = c.tool_name,
    tc.input_summary = c.input_summary, tc.ok = c.ok, tc.error = c.error,
    tc.agent_id = c.agent_id, tc.timestamp = c.timestamp, tc.layer = 1
MERGE (tool:Tool {name: c.tool_name})
MERGE (t)-[:MADE]->(tc)
MERGE (tc)-[:USED]->(tool);

UNWIND $files AS f
MERGE (n:File {path: f.path})
SET n.layer = 1, n.detected_by = f.how;

UNWIND $tool_calls AS c
UNWIND c.files AS p
MATCH (tc:ToolCall {id: c.id}), (f:File {path: p})
MERGE (tc)-[:TOUCHED]->(f);

UNWIND $skills AS k
MERGE (n:Skill {name: k.name})
SET n.layer = 1;

UNWIND [c IN $tool_calls WHERE c.skill IS NOT NULL] AS c
MATCH (tc:ToolCall {id: c.id}), (k:Skill {name: c.skill})
MERGE (tc)-[:INVOKED]->(k);

// Derived counters (recomputed on every load, so they stay correct across sessions).
MATCH (tool:Tool) OPTIONAL MATCH (tool)<-[:USED]-(c:ToolCall)
WITH tool, count(c) AS n SET tool.call_count = n;

MATCH (f:File) OPTIONAL MATCH (f)<-[:TOUCHED]-(c:ToolCall)
WITH f, count(c) AS n SET f.touch_count = n;
