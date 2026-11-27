// Step 2 — constraints and indexes. Idempotent (IF NOT EXISTS); run once per store.
// Verified against Relate 1.3.0 (docs/reference/cypher-syntax.md: CREATE CONSTRAINT / CREATE INDEX).

// layer 1 — episodic, deterministic
CREATE CONSTRAINT session_id   IF NOT EXISTS FOR (s:Session)  REQUIRE s.id   IS UNIQUE;
CREATE CONSTRAINT turn_id      IF NOT EXISTS FOR (t:Turn)     REQUIRE t.id   IS UNIQUE;
CREATE CONSTRAINT toolcall_id  IF NOT EXISTS FOR (c:ToolCall) REQUIRE c.id   IS UNIQUE;
CREATE CONSTRAINT tool_name    IF NOT EXISTS FOR (t:Tool)     REQUIRE t.name IS UNIQUE;
CREATE CONSTRAINT file_path    IF NOT EXISTS FOR (f:File)     REQUIRE f.path IS UNIQUE;
CREATE CONSTRAINT skill_name   IF NOT EXISTS FOR (k:Skill)    REQUIRE k.name IS UNIQUE;

// layer 2 — semantic, model-generated (keys are session-scoped except Topic.slug)
CREATE CONSTRAINT topic_slug   IF NOT EXISTS FOR (t:Topic)    REQUIRE t.slug IS UNIQUE;
CREATE CONSTRAINT decision_key IF NOT EXISTS FOR (d:Decision) REQUIRE d.key  IS UNIQUE;
CREATE CONSTRAINT question_key IF NOT EXISTS FOR (q:Question) REQUIRE q.key  IS UNIQUE;

CREATE INDEX turn_session      IF NOT EXISTS FOR (t:Turn)     ON (t.session_id);
CREATE INDEX turn_index        IF NOT EXISTS FOR (t:Turn)     ON (t.index);
CREATE INDEX toolcall_session  IF NOT EXISTS FOR (c:ToolCall) ON (c.session_id);
CREATE INDEX decision_session  IF NOT EXISTS FOR (d:Decision) ON (d.session_id);
CREATE INDEX decision_status   IF NOT EXISTS FOR (d:Decision) ON (d.status);
CREATE INDEX question_status   IF NOT EXISTS FOR (q:Question) ON (q.status);
