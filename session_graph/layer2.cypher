// Step 5 — layer 2 (semantic, model-generated). Idempotent: MERGE on ids.
// Parameters come from tagged.json: $session_id, $model, $topics, $decisions, $questions.
// Every node and edge written here carries source = "model" and a confidence;
// nothing here touches a layer-1 property.
// Re-running for a session first clears that session's previous layer-2 output, so a
// re-tag that drops a topic or decision leaves nothing stale behind.

MATCH (:Turn {session_id: $session_id})-[r:DISCUSSES]->(:Topic) DELETE r;
MATCH (n:Decision {session_id: $session_id}) DETACH DELETE n;
MATCH (n:Question {session_id: $session_id}) DETACH DELETE n;
MATCH (t:Topic) WHERE NOT (t)<-[:DISCUSSES]-() DETACH DELETE t;

UNWIND $topics AS t
MERGE (n:Topic {slug: t.slug})
SET n.source = 'model', n.layer = 2,
    n.confidence = CASE WHEN n.confidence IS NULL OR t.confidence > n.confidence
                        THEN t.confidence ELSE n.confidence END
WITH n, t
UNWIND t.turn_indexes AS ti
MATCH (turn:Turn {session_id: $session_id, index: ti})
MERGE (turn)-[r:DISCUSSES]->(n)
SET r.source = 'model', r.confidence = t.confidence, r.model = $model;

UNWIND $decisions AS d
MERGE (n:Decision {key: $session_id + ':' + d.id})
SET n.id = d.id, n.session_id = $session_id, n.text = d.text, n.status = d.status,
    n.source = 'model', n.confidence = d.confidence, n.model = $model, n.layer = 2
WITH n, d
MATCH (turn:Turn {session_id: $session_id, index: d.turn_index})
MERGE (n)-[r:DECIDED_IN]->(turn)
SET r.source = 'model', r.confidence = d.confidence;

UNWIND $decisions AS d
UNWIND [x IN d.topics] AS slug
MATCH (n:Decision {key: $session_id + ':' + d.id}), (t:Topic {slug: slug})
MERGE (n)-[r:ABOUT]->(t)
SET r.source = 'model', r.confidence = d.confidence;

UNWIND [d IN $decisions WHERE d.supersedes IS NOT NULL] AS d
MATCH (a:Decision {key: $session_id + ':' + d.id}),
      (b:Decision {key: $session_id + ':' + d.supersedes})
MERGE (a)-[r:SUPERSEDES]->(b)
SET r.source = 'model', r.confidence = d.confidence;

UNWIND [d IN $decisions WHERE d.defers IS NOT NULL] AS d
MATCH (a:Decision {key: $session_id + ':' + d.id}),
      (b:Decision {key: $session_id + ':' + d.defers})
MERGE (a)-[r:DEFERS]->(b)
SET r.source = 'model', r.confidence = d.confidence;

UNWIND $questions AS q
MERGE (n:Question {key: $session_id + ':' + q.id})
SET n.id = q.id, n.session_id = $session_id, n.text = q.text, n.status = q.status,
    n.source = 'model', n.confidence = q.confidence, n.model = $model, n.layer = 2
WITH n, q
MATCH (turn:Turn {session_id: $session_id, index: q.raised_in})
MERGE (n)-[r:RAISED_IN]->(turn)
SET r.source = 'model', r.confidence = q.confidence;

UNWIND [q IN $questions WHERE q.resolved_in IS NOT NULL] AS q
MATCH (n:Question {key: $session_id + ':' + q.id}),
      (turn:Turn {session_id: $session_id, index: q.resolved_in})
MERGE (n)-[r:RESOLVED_IN]->(turn)
SET r.source = 'model', r.confidence = q.confidence;
