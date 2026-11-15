"""The link the crew gets: /medic/<incident>?t=<token>, and the card image it unfurls into.

The token is an HMAC of the incident id, so a guessed incident id gives nothing: the page and its picture
both need the token that was sent to the crew.
"""

import hashlib
import hmac

from app.config import get_settings


def _key() -> bytes:
    settings = get_settings()
    if settings.share_secret:
        return settings.share_secret.encode()
    # no secret configured: derive one from the service-role key (one way, so the key is not exposed)
    return hashlib.sha256(b"beeline-share:" + settings.supabase_service_role_key.encode()).digest()


def make_token(incident_id: str) -> str:
    return hmac.new(_key(), incident_id.encode(), hashlib.sha256).hexdigest()[:32]


def check_token(incident_id: str, token: str) -> bool:
    return bool(token) and hmac.compare_digest(make_token(incident_id), token)


def _base() -> str:
    return (get_settings().public_api_url or "http://localhost:8000").rstrip("/")


def _query(incident_id: str, version: int | str | None) -> str:
    # the version only makes the URL new for each route, so chat apps (which cache previews by URL) re-fetch it
    return f"t={make_token(incident_id)}" + (f"&v={version}" if version else "")


def medic_url(incident_id: str, version: int | str | None = None) -> str:
    return f"{_base()}/medic/{incident_id}?{_query(incident_id, version)}"


def card_url(incident_id: str, version: int | str | None = None) -> str:
    return f"{_base()}/medic/{incident_id}/card.png?{_query(incident_id, version)}"
