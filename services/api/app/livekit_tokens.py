# pyright: reportMissingImports=false
"""LiveKit token issuance boundary for GilJob v2.

This module signs participant join tokens when LiveKit credentials are
configured. Local media mode intentionally separates the server/container URL
from the browser-facing URL because Docker-internal addresses such as
``ws://livekit:7880`` are not generally reachable by a browser.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import os
from typing import Any

LIVEKIT_TOKEN_TTL_SECONDS = int(os.getenv("LIVEKIT_TOKEN_TTL_SECONDS", os.getenv("SESSION_TOKEN_TTL_SECONDS", "7200")))


@dataclass(frozen=True)
class LiveKitSettings:
    internal_url: str
    public_url: str
    api_key: str
    api_secret: str
    token_ttl_seconds: int = LIVEKIT_TOKEN_TTL_SECONDS

    @property
    def url(self) -> str:
        """Backward-compatible alias for the browser-facing URL."""
        return self.public_url


class LiveKitConfigurationError(RuntimeError):
    """Raised when media token issuance is required but not configured."""


def _env_truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _getenv_stripped(name: str) -> str:
    return os.getenv(name, "").strip()


def load_livekit_settings() -> LiveKitSettings | None:
    """Load optional LiveKit settings from env.

    Preferred local/self-hosted contract:
    - LIVEKIT_INTERNAL_URL: API/container-to-LiveKit address, e.g. ws://livekit:7880
    - LIVEKIT_PUBLIC_URL: browser-facing address, e.g. ws://127.0.0.1:7880

    LIVEKIT_URL remains a compatibility fallback for older one-URL scaffold
    development runs only. Required/prod media runs must set both explicit URLs
    so the browser/container addressing split cannot be bypassed.
    """
    legacy_url = _getenv_stripped("LIVEKIT_URL")
    required_mode = _env_truthy(os.getenv("LIVEKIT_REQUIRED")) or os.getenv("GILJOB_ENV", "development").lower() == "production"
    explicit_internal_url = _getenv_stripped("LIVEKIT_INTERNAL_URL")
    explicit_public_url = _getenv_stripped("LIVEKIT_PUBLIC_URL")
    internal_url = explicit_internal_url or ("" if required_mode else legacy_url)
    public_url = explicit_public_url or ("" if required_mode else legacy_url)
    api_key = _getenv_stripped("LIVEKIT_API_KEY")
    api_secret = _getenv_stripped("LIVEKIT_API_SECRET")
    url_label = "LIVEKIT_INTERNAL_URL" if required_mode else "LIVEKIT_INTERNAL_URL or LIVEKIT_URL"
    public_label = "LIVEKIT_PUBLIC_URL" if required_mode else "LIVEKIT_PUBLIC_URL or LIVEKIT_URL"
    missing = [
        name
        for name, value in (
            (url_label, internal_url),
            (public_label, public_url),
            ("LIVEKIT_API_KEY", api_key),
            ("LIVEKIT_API_SECRET", api_secret),
        )
        if not value
    ]
    if missing:
        if required_mode:
            raise LiveKitConfigurationError("missing LiveKit configuration: " + ", ".join(missing))
        return None

    return LiveKitSettings(
        internal_url=internal_url,
        public_url=public_url,
        api_key=api_key,
        api_secret=api_secret,
        token_ttl_seconds=int(os.getenv("LIVEKIT_TOKEN_TTL_SECONDS", str(LIVEKIT_TOKEN_TTL_SECONDS))),
    )


def _create_livekit_join_token(settings: LiveKitSettings, *, identity: str, name: str, room_name: str) -> str:
    """Create a signed LiveKit room join token using the official Python SDK."""
    from livekit import api  # type: ignore[import-not-found]

    token_builder = (
        api.AccessToken(settings.api_key, settings.api_secret)
        .with_identity(identity)
        .with_name(name)
        .with_ttl(timedelta(seconds=settings.token_ttl_seconds))
        .with_grants(
            api.VideoGrants(
                room_join=True,
                room=room_name,
                can_publish=True,
                can_subscribe=True,
                can_publish_data=True,
            )
        )
    )
    return str(token_builder.to_jwt())


def issue_candidate_livekit_token(*, room_name: str, session_id: str) -> dict[str, Any]:
    """Return the LiveKit object for the public session response."""
    identity = f"candidate-{session_id}"
    participant_name = "candidate"
    settings = load_livekit_settings()

    if settings is None:
        return {
            "url": None,
            "publicUrl": None,
            "roomName": room_name,
            "participantIdentity": identity,
            "participantName": participant_name,
            "candidateToken": None,
            "tokenStatus": "not_configured",
            "deferredReason": "livekit_credentials_missing",
        }

    candidate_token = _create_livekit_join_token(
        settings,
        identity=identity,
        name=participant_name,
        room_name=room_name,
    )
    return {
        # url is retained for existing clients; it is always browser-facing.
        "url": settings.public_url,
        "publicUrl": settings.public_url,
        "roomName": room_name,
        "participantIdentity": identity,
        "participantName": participant_name,
        "candidateToken": candidate_token,
        "tokenStatus": "issued",
        "tokenTtlSeconds": settings.token_ttl_seconds,
    }
