"""Download of the Arbeitnow job feed (paginated, no authentication)."""

from collections.abc import Iterator

import httpx

FEED_URL = "https://www.arbeitnow.com/api/job-board-api"


def iter_feed(client: httpx.Client, max_pages: int) -> Iterator[dict]:
    """Yield the postings of pages 1..max_pages; stops at an empty page or when ``links.next`` is empty."""
    for page in range(1, max_pages + 1):
        response = client.get(FEED_URL, params={"page": page})
        response.raise_for_status()
        body = response.json()
        data = body.get("data") if isinstance(body, dict) else None
        if not data:
            return
        for item in data:
            if isinstance(item, dict):
                yield item
        links = body.get("links")
        if not (isinstance(links, dict) and links.get("next")):
            return
