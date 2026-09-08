-- Milestone 4 — conversational memory.
--
-- **No `turn` table, and that is deliberate.**
--
-- The obvious design was a table recording (session, seq, question, answer).
-- `query_run` already records exactly that, for every question ever asked, and has
-- since Milestone -1: `question`, `final_answer`, `strategy`, `started_at`. A second
-- table would be a second source of truth for "what has this session asked", and the
-- two would eventually disagree — most likely on a run that failed halfway, where one
-- has a row and the other does not.
--
-- What `query_run` cannot express is where the *current* conversation begins. A
-- student pressing "New conversation" wants the follow-up chain forgotten; they do not
-- want the runs deleted, because the Trace page lists every run in the session and
-- losing them would break the "read any run" story in order to fix the memory one.
--
-- So the conversation is a watermark over runs that already exist. One row per
-- session, absent until somebody starts a new conversation — and absent means "the
-- whole session", which is the right behaviour for every session that existed before
-- this table did.
--
-- A table rather than a column on `session`, for a mechanical reason worth recording:
-- `backend/store/db.py` replays every migration on every startup and depends on
-- `IF NOT EXISTS` to make that harmless. SQLite has no `ALTER TABLE ... ADD COLUMN IF
-- NOT EXISTS`, so a column here would raise "duplicate column name" on the second
-- boot. Adding a table keeps the runner's one contract intact.
CREATE TABLE IF NOT EXISTS conversation (
    session_id TEXT PRIMARY KEY REFERENCES session(id) ON DELETE CASCADE,
    -- Only runs started at or after this are part of the current conversation.
    since      TEXT NOT NULL
);
