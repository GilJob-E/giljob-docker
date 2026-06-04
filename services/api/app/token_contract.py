"""Session/report token contract for the GilJob v2 API.

This module intentionally separates public raw tokens from server-side records.
Only HMAC digests are suitable for persistence. The current scaffold keeps those
records in-process; the matching Postgres schema lives in ``services/api/db``.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import os
import re
import secrets
import uuid

from app.livekit_tokens import issue_candidate_livekit_token

SESSION_TTL_SECONDS = int(os.getenv("SESSION_TOKEN_TTL_SECONDS", "7200"))
REPORT_TTL_SECONDS = int(os.getenv("REPORT_TOKEN_TTL_SECONDS", "2592000"))
TOKEN_HASH_VERSION = "hmac-sha256:v1"
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")

_DEFAULT_DEV_SECRETS = {
    "session": "giljob-v2-dev-session-hash-secret-change-before-production",
    "report": "giljob-v2-dev-report-hash-secret-change-before-production",
}
_ENV_SECRET_NAMES = {
    "session": "SESSION_TOKEN_HASH_SECRET",
    "report": "REPORT_TOKEN_HASH_SECRET",
}


def utc_now() -> datetime:
    """Return an aware UTC timestamp rounded to seconds for stable contracts."""
    return datetime.now(timezone.utc).replace(microsecond=0)


def isoformat_z(value: datetime) -> str:
    """Format a UTC datetime as an RFC3339-style string ending with Z."""
    if value.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _secret_for(purpose: str) -> bytes:
    if purpose not in _ENV_SECRET_NAMES:
        raise ValueError(f"unsupported token purpose: {purpose}")

    env_name = _ENV_SECRET_NAMES[purpose]
    configured = os.getenv(env_name)
    if configured:
        return configured.encode("utf-8")

    if os.getenv("GILJOB_ENV", "development").lower() == "production":
        raise RuntimeError(f"{env_name} is required when GILJOB_ENV=production")

    return _DEFAULT_DEV_SECRETS[purpose].encode("utf-8")


def generate_token(prefix: str) -> str:
    """Generate an opaque bearer token with a readable contract prefix."""
    return f"{prefix}_{secrets.token_urlsafe(32)}"


def hash_token(raw_token: str, purpose: str) -> str:
    """Hash a raw token for server-side storage using purpose-separated HMAC."""
    if not raw_token:
        raise ValueError("raw_token must not be empty")
    message = f"giljob-v2:{TOKEN_HASH_VERSION}:{purpose}:{raw_token}".encode("utf-8")
    digest = hmac.new(_secret_for(purpose), message, hashlib.sha256).hexdigest()
    return f"{TOKEN_HASH_VERSION}:{purpose}:{digest}"


def normalize_requested_session_id(value: object | None) -> str | None:
    """Return a safe caller-selected session id, or None for generated ids."""
    if value is None:
        return None
    session_id = str(value).strip()
    if not SESSION_ID_RE.fullmatch(session_id):
        raise ValueError("invalid session id")
    return session_id


def issue_session(
    now: datetime | None = None,
    requested_role: str = "candidate",
    requested_session_id: object | None = None,
) -> dict[str, dict[str, object]]:
    """Create the public response and private record for a new interview session.

    The returned ``public`` object contains raw bearer tokens exactly once for
    delivery to the caller. The returned ``stored`` object is the only structure
    suitable for persistence and contains token hashes only.
    """
    created_at = (now or utc_now()).astimezone(timezone.utc).replace(microsecond=0)
    session_expires_at = created_at + timedelta(seconds=SESSION_TTL_SECONDS)
    report_expires_at = created_at + timedelta(seconds=REPORT_TTL_SECONDS)

    session_id = normalize_requested_session_id(requested_session_id) or str(uuid.uuid4())
    room_name = f"giljob-session-{session_id}"
    session_token = generate_token("gj_session")
    report_token = generate_token("gj_report")

    stored = {
        "sessionId": session_id,
        "roomName": room_name,
        "sessionTokenHash": hash_token(session_token, "session"),
        "reportTokenHash": hash_token(report_token, "report"),
        "tokenHashVersion": TOKEN_HASH_VERSION,
        "sessionTokenExpiresAt": isoformat_z(session_expires_at),
        "reportTokenExpiresAt": isoformat_z(report_expires_at),
        "state": "created",
        "stateVersion": 1,
        "createdAt": isoformat_z(created_at),
        "requestedRole": requested_role,
    }
    public = {
        "sessionId": session_id,
        "roomName": room_name,
        "sessionToken": session_token,
        "sessionTokenTtlSeconds": SESSION_TTL_SECONDS,
        "sessionTokenExpiresAt": isoformat_z(session_expires_at),
        "reportToken": report_token,
        "reportTokenTtlSeconds": REPORT_TTL_SECONDS,
        "reportTokenExpiresAt": isoformat_z(report_expires_at),
        "tokenType": "bearer",
        "state": "created",
        "stateVersion": 1,
        "livekit": issue_candidate_livekit_token(
            room_name=room_name,
            session_id=session_id,
        ),
    }
    return {"public": public, "stored": stored}
