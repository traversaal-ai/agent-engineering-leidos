-- Milestone -1 — initial schema.
--
-- Plain .sql applied in filename order by backend/store/db.py. No ORM and no
-- migration framework: the schema is small, it mirrors the ER diagram in System
-- Design Section 7 closely enough to read side by side, and a student can see
-- exactly what is stored. Add 002_*.sql for the next change rather than editing
-- this file — it has already run on machines you do not control.

CREATE TABLE IF NOT EXISTS session (
    id                TEXT PRIMARY KEY,
    -- SHA-256 of the bearer token, never the token itself. The session store
    -- ends up in a shared repo checkout or a student's laptop backup more often
    -- than anyone plans for.
    token_hash        TEXT NOT NULL UNIQUE,
    created_at        TEXT NOT NULL,
    expires_at        TEXT NOT NULL,
    -- Running totals for cap enforcement. Denormalised on purpose: the cap is
    -- checked before every query, and that check must not depend on summing the
    -- whole agent_step table each time.
    spent_usd         TEXT NOT NULL DEFAULT '0',
    request_count     INTEGER NOT NULL DEFAULT 0,
    -- The caps in force for this session, captured at creation so that changing
    -- the server default mid-workshop cannot retroactively move a student's
    -- limit up or down.
    cap_cost_usd      TEXT NOT NULL,
    cap_requests      INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_session_expires ON session(expires_at);

CREATE TABLE IF NOT EXISTS document (
    id             TEXT PRIMARY KEY,
    session_id     TEXT NOT NULL REFERENCES session(id) ON DELETE CASCADE,
    filename       TEXT NOT NULL,
    format         TEXT NOT NULL,
    byte_size      INTEGER NOT NULL DEFAULT 0,
    upload_time    TEXT NOT NULL,
    -- 'pending' | 'ready' | 'failed'. PRD Section 6 requires a per-file
    -- success/failure status with a reason, so a partial upload has to be
    -- representable rather than all-or-nothing.
    status         TEXT NOT NULL DEFAULT 'pending',
    error          TEXT
);

CREATE INDEX IF NOT EXISTS idx_document_session ON document(session_id);

CREATE TABLE IF NOT EXISTS query_run (
    id            TEXT PRIMARY KEY,
    session_id    TEXT NOT NULL REFERENCES session(id) ON DELETE CASCADE,
    trace_id      TEXT NOT NULL,
    strategy      TEXT NOT NULL,
    question      TEXT NOT NULL,
    final_answer  TEXT,
    status        TEXT NOT NULL DEFAULT 'running',
    error         TEXT,
    started_at    TEXT NOT NULL,
    latency_ms    INTEGER NOT NULL DEFAULT 0,
    cost_usd      TEXT NOT NULL DEFAULT '0'
);

CREATE INDEX IF NOT EXISTS idx_query_run_session ON query_run(session_id);
CREATE INDEX IF NOT EXISTS idx_query_run_trace   ON query_run(trace_id);

-- One question run across both strategies. A partially-failing Compare run needs
-- somewhere to record which strategy failed — Section 11 requires the failure be shown
-- in that strategy's column, not left blank.
CREATE TABLE IF NOT EXISTS comparison_run (
    id           TEXT PRIMARY KEY,
    session_id   TEXT NOT NULL REFERENCES session(id) ON DELETE CASCADE,
    question     TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    metrics      TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_comparison_session ON comparison_run(session_id);

-- A `graph_index` table stood here, holding build metrics for a graph retriever that
-- was specified and never written. It had no Python reader at any point. Removed from
-- this file *and* dropped by `004_drop_graph_index.sql` — see that file for why both
-- were needed.
