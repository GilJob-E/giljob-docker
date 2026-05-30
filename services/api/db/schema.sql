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
