"""The backend's only way to reach Photon: the photon-sidecar service next to it.

The sidecar holds the Photon keys and talks to Photon; this client just posts to it, with a shared secret.
"""

from functools import lru_cache

import httpx

from app.config import get_settings

TIMEOUT_S = 8


class SidecarClient:
    def __init__(self, base_url: str, secret: str, client: httpx.AsyncClient | None = None):
        self._base = base_url.rstrip("/")
        self._headers = {"X-Photon-Secret": secret}
        self._client = client

    async def _post(self, path: str, body: dict) -> dict:
        if self._client is not None:
            response = await self._client.post(
                f"{self._base}{path}", json=body, headers=self._headers
            )
        else:
            async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
                response = await client.post(
                    f"{self._base}{path}", json=body, headers=self._headers
                )
        response.raise_for_status()
        return response.json()

    async def send(
        self, *, incident_id: str, thread_id: str, sender_id: str, text: str | None, url: str | None
    ) -> dict:
        """Post into a crew member's chat: the text, then the link on its own so that it unfurls."""
        body = {
            "incident_id": incident_id,
            "thread_id": thread_id,
            "sender_id": sender_id,
            "text": text,
            "url": url,
        }
        return await self._post("/send", body)

    async def assign(self, *, handle: str, name: str | None) -> dict:
        """Give a crew member a line to text. Returns {assigned_phone_number, ...}."""
        return await self._post("/assign", {"handle": handle, "name": name})


@lru_cache
def get_sidecar() -> SidecarClient:
    settings = get_settings()
    if not settings.sidecar_url:
        raise RuntimeError("SIDECAR_URL is not set")
    return SidecarClient(settings.sidecar_url, settings.photon_shared_secret)
