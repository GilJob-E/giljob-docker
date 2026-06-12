-- GilJob v2 M2 session-token persistence contract.
-- Raw session/report tokens MUST NOT be stored in this table.

CREATE TABLE IF NOT EXISTS interview_sessions (
    session_id UUID PRIMARY KEY,
    room_name TEXT NOT NULL UNIQUE,
    session_token_hash TEXT NOT NULL,
    report_token_hash TEXT NOT NULL,
    token_hash_version TEXT NOT NULL,
    session_token_expires_at TIMESTAMPTZ NOT NULL,
    report_token_expires_at TIMESTAMPTZ NOT NULL,
    state TEXT NOT NULL DEFAULT 'created',
    state_version INTEGER NOT NULL DEFAULT 1,
    requested_role TEXT NOT NULL DEFAULT 'candidate',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (state_version >= 1),
    CHECK (session_token_hash <> report_token_hash),
    CHECK (session_token_hash LIKE 'hmac-sha256:v1:session:%'),
    CHECK (report_token_hash LIKE 'hmac-sha256:v1:report:%')
);

CREATE INDEX IF NOT EXISTS idx_interview_sessions_room_name
    ON interview_sessions (room_name);

CREATE UNIQUE INDEX IF NOT EXISTS idx_interview_sessions_session_token_hash
    ON interview_sessions (session_token_hash);

CREATE UNIQUE INDEX IF NOT EXISTS idx_interview_sessions_report_token_hash
    ON interview_sessions (report_token_hash);

-- Per-turn Q&A persistence for report generation.
-- Composite PRIMARY KEY (session_id, turn_id) is the lookup index used by the
-- report endpoint (GET /api/interviews/:id/report). The candidate answer of
-- record is the analysis-engine transcript; the question is brokered by the API.
CREATE TABLE IF NOT EXISTS interview_turns (
    session_id TEXT NOT NULL,
    turn_id INTEGER NOT NULL,
    question TEXT,
    answer TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (session_id, turn_id),
    CHECK (turn_id >= 1)
);

-- Fetch all turns of one interview, ordered by turn_id, in a single query.
CREATE INDEX IF NOT EXISTS idx_interview_turns_session
    ON interview_turns (session_id, turn_id);

-- Per-turn non-verbal / evaluation signals produced by the analysis-engine
-- (GilJobE). The interview signal stream is per-window (16s eval windows); this
-- table holds the records belonging to one turn, segmented by turn_end markers.
--
-- Same composite key as interview_turns so the report endpoint joins them 1:1:
--     interview_turns        (session_id, turn_id) -> question, answer   [api writes]
--     interview_turn_signals (session_id, turn_id) -> signals(jsonb)     [analysis writes]
--
--   signals  : raw eval records for the turn (kor-signals.json shape:
--              eval.objective_vocal / objective_visual / critique / key_observations).
--              Aggregation (window -> turn mean/sum, visualMeasurable coverage) is
--              applied at report build time, keeping this row the source of truth.
--   giljobe_ref : pin of the GilJobE build that produced the objective_* schema.
CREATE TABLE IF NOT EXISTS interview_turn_signals (
    session_id TEXT NOT NULL,
    turn_id INTEGER NOT NULL,
    signals JSONB NOT NULL,
    window_count INTEGER NOT NULL DEFAULT 0,
    visual_measurable BOOLEAN NOT NULL DEFAULT FALSE,
    giljobe_ref TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (session_id, turn_id),
    CHECK (turn_id >= 1),
    CHECK (window_count >= 0),
    -- Signals exist only for a known turn; cascade if that turn is removed.
    FOREIGN KEY (session_id, turn_id)
        REFERENCES interview_turns (session_id, turn_id)
        ON DELETE CASCADE
);

-- Fetch all signal rows of one interview, ordered by turn_id, in a single query
-- (mirrors interview_turns so the report JOIN stays index-aligned).
CREATE INDEX IF NOT EXISTS idx_interview_turn_signals_session
    ON interview_turn_signals (session_id, turn_id);
