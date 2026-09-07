-- Milestone 4 — two corpora in one session.
--
-- A session can hold the demo fixture set *and* up to five of the student's own
-- documents, and a toggle decides which one is searched. Before this, it could hold
-- neither-and-then-one: the demo set is exactly five files and the limit was five per
-- session, so `existing + 5 > 5` was true for **any** existing document. One upload
-- permanently blocked the demo corpus, and with no delete route the only escape was
-- Start over.
--
-- **A table rather than a column on `document`, and not by preference.**
-- `backend/store/db.py` replays every migration on every startup and depends on
-- `IF NOT EXISTS` to make that harmless. SQLite has no
-- `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`, so a column here would raise "duplicate
-- column name" on the second boot. `002_conversation.sql` hit the same wall and records
-- the same workaround.
--
-- **Explicit rather than derived from the filename.** The frontend has been telling the
-- demo corpus apart by comparing filenames against the demo set's, which is adequate as
-- a gate and wrong as an identity: nothing stops a student uploading a file called
-- `acme-msa-2026.md`, and from that point the two corpora would disagree about which
-- documents they hold.
--
-- Note what is *not* here: which corpus is currently active. That is a view preference
-- rather than a fact about the session — it lives in a cookie beside the pace and cache
-- toggles, so two people looking at one session can look at different corpora.
CREATE TABLE IF NOT EXISTS document_corpus (
    document_id TEXT PRIMARY KEY REFERENCES document(id) ON DELETE CASCADE,
    -- 'demo' | 'mine'. Not constrained here: the closed set lives in
    -- `ai_backend/contracts/pipeline.py::CORPORA`, and a CHECK duplicating it would be
    -- a second place to update and a migration to write when a third corpus appears.
    corpus      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_document_corpus ON document_corpus(corpus);
