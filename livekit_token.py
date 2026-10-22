"""Generate LiveKit access tokens (server-side) for the frontend/client."""
from __future__ import annotations

from config import settings


def generate_token(identity: str, room: str | None = None) -> str:
    from livekit.api import AccessToken, VideoGrant

    if not (settings.livekit_api_key and settings.livekit_api_secret):
        raise RuntimeError("LiveKit API key/secret not configured in .env")

    token = AccessToken(settings.livekit_api_key,
                        settings.livekit_api_secret,
                        identity=identity)
    grant = VideoGrant(room=room or settings.livekit_room)
    grant.add_track("audio", can_publish=True, can_subscribe=True)
    token.add_grant(grant)
    return token.to_jwt()
