from __future__ import annotations

import httpx

TIMEOUT = 5.0


async def check_url_reachable(url: str) -> bool:
    """Check if a URL is reachable. HEAD first, GET fallback. 5s timeout."""
    if not url or not url.startswith(("http://", "https://")):
        return False

    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
        # Try HEAD first
        try:
            resp = await client.head(url)
            if resp.status_code < 400:
                return True
        except Exception:
            pass

        # Fallback to GET
        try:
            resp = await client.get(url)
            return resp.status_code < 400
        except Exception:
            return False


def check_url_reachable_sync(url: str) -> bool:
    """Synchronous version for use in non-async graph nodes."""
    if not url or not url.startswith(("http://", "https://")):
        return False

    with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client:
        try:
            resp = client.head(url)
            if resp.status_code < 400:
                return True
        except Exception:
            pass

        try:
            resp = client.get(url)
            return resp.status_code < 400
        except Exception:
            return False
