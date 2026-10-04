"""Reverse-image search through Google Cloud Vision *web detection*.

Vision accepts the image bytes directly (no public link needed), which is what makes it usable
for uploads. It is the one real search backend that is not open source, and it sends the image
to Google: it only runs when ``VERIXA_GOOGLE_VISION_API_KEY`` is set and the image backend is
chosen explicitly. The key travels in a header, never in the URL, and is never logged.

Matches are bands, not scores: full-image matches rank above partial matches above visually
similar images, and ``similarity`` is the band (1.0 / 0.7 / 0.4), not a measured value.
"""

import base64
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from app.providers.search.base import (
    GENERIC_LIMITATIONS,
    SearchResult,
    SourceMatch,
    SourceSearchError,
)

ENDPOINT = "https://vision.googleapis.com/v1/images:annotate"
# The request body (base64) must stay under 10 MB.
MAX_IMAGE_BYTES = 7_000_000
LIST_PRICE_USD = 0.0035  # per image beyond the monthly free allowance


def _page_match(page: dict[str, Any], now: datetime) -> SourceMatch | None:
    url = page.get("url")
    if not url:
        return None
    full = bool(page.get("fullMatchingImages"))
    return SourceMatch(
        provider="google_vision",
        url=str(url),
        title=(str(page["pageTitle"]) if page.get("pageTitle") else None),
        snippet=None,
        similarity=1.0 if full else 0.7,
        source_kind="web_page",
        matched_phrase=None,
        published_at=None,
        discovered_at=now,
        raw={"band": "full" if full else "partial", "kind": "page"},
    )


def _image_match(
    item: dict[str, Any], band: str, score: float, now: datetime
) -> SourceMatch | None:
    url = item.get("url")
    if not url:
        return None
    return SourceMatch(
        provider="google_vision",
        url=str(url),
        title=None,
        snippet=None,
        similarity=score,
        source_kind="image",
        matched_phrase=None,
        published_at=None,
        discovered_at=now,
        raw={"band": band, "kind": "image"},
    )


class GoogleVisionImageSearch:
    name = "google_vision"
    version = "v1"
    cache_scope = "v1"

    def __init__(
        self,
        *,
        api_key: str,
        max_results: int,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key.strip():
            raise SourceSearchError("VERIXA_GOOGLE_VISION_API_KEY is not set")
        self._key = api_key
        self._max = max_results
        self._timeout = timeout_seconds
        self._transport = transport

    async def search_image(self, content: bytes, *, metadata: dict[str, Any]) -> SearchResult:
        if len(content) > MAX_IMAGE_BYTES:
            raise SourceSearchError(
                f"the image is larger than {MAX_IMAGE_BYTES // 1_000_000} MB, which Google "
                "Vision web detection does not accept"
            )
        body = {
            "requests": [
                {
                    "image": {"content": base64.b64encode(content).decode("ascii")},
                    "features": [{"type": "WEB_DETECTION", "maxResults": self._max}],
                }
            ]
        }
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport, follow_redirects=False
            ) as client:
                resp = await client.post(
                    ENDPOINT,
                    json=body,
                    headers={"X-Goog-Api-Key": self._key},
                )
        except httpx.TimeoutException as exc:
            raise SourceSearchError("Google Vision timed out") from exc
        except httpx.HTTPError as exc:
            raise SourceSearchError(
                f"Google Vision request failed ({exc.__class__.__name__})"
            ) from exc
        latency = int((time.perf_counter() - started) * 1000)
        if resp.status_code != 200:
            raise SourceSearchError(f"Google Vision returned HTTP {resp.status_code}")
        try:
            first = resp.json()["responses"][0]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise SourceSearchError("Google Vision returned an unexpected payload") from exc
        error = first.get("error")
        if error:
            raise SourceSearchError(f"Google Vision error {error.get('code', '?')}")
        web = first.get("webDetection") or {}

        now = datetime.now(UTC)
        merged: dict[str, SourceMatch] = {}
        for page in web.get("pagesWithMatchingImages") or []:
            m = _page_match(page, now)
            if m:
                merged.setdefault(m.url, m)
        for key, band, score in (
            ("fullMatchingImages", "full", 1.0),
            ("partialMatchingImages", "partial", 0.7),
            ("visuallySimilarImages", "similar", 0.4),
        ):
            for item in web.get(key) or []:
                m = _image_match(item, band, score, now)
                if m:
                    merged.setdefault(m.url, m)
        matches = list(merged.values())[: self._max * 2]
        return SearchResult(
            provider=self.name,
            provider_version=self.version,
            modality="image",
            matches=matches,
            latency_ms=latency,
            estimated_cost=LIST_PRICE_USD,
            limitations=[
                "The image was sent to Google Cloud Vision for this search.",
                "similarity is a band set by Google's match category (full 1.0, partial 0.7, "
                "visually similar 0.4), not a measured score.",
                "Google reports no publication dates, so a hit says nothing about which copy "
                "is older.",
                *GENERIC_LIMITATIONS,
            ],
        )
