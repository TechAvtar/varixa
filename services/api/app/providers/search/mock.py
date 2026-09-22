"""Mock search providers: deterministic, self-declared, no network.

They exercise the full persistence/UI path. Results point at the reserved
``.invalid`` TLD so they can never be mistaken for real sources.
"""

import hashlib
from datetime import UTC, datetime
from typing import Any

from app.providers.search.base import GENERIC_LIMITATIONS, SearchResult, SourceMatch

MOCK_VERSION = "0.0"
_MOCK_NOTE = (
    "This is a MOCK search provider: matches are synthetic placeholders derived from the "
    "content hash and do not correspond to any real source."
)


def _bucket(data: bytes, n: int) -> int:
    return int.from_bytes(hashlib.sha256(b"verixa-mock-search:" + data).digest()[:2], "big") % n


class MockImageSourceSearch:
    name = "mock"

    async def search_image(self, content: bytes, *, metadata: dict[str, Any]) -> SearchResult:
        now = datetime.now(UTC)
        count = _bucket(content, 3)  # 0, 1 or 2 synthetic hits
        digest = hashlib.sha256(content).hexdigest()[:10]
        matches = [
            SourceMatch(
                provider=self.name,
                url=f"https://mock-source-{i + 1}.example.invalid/images/{digest}",
                title=f"Mock reverse-image result {i + 1}",
                snippet=None,
                similarity=round(0.95 - 0.2 * i, 2),
                source_kind="image",
                matched_phrase=None,
                published_at=None,
                discovered_at=now,
                raw={"mock": True, "rank": i + 1},
            )
            for i in range(count)
        ]
        return SearchResult(
            provider=self.name,
            provider_version=MOCK_VERSION,
            modality="image",
            matches=matches,
            latency_ms=0,
            estimated_cost=0.0,
            limitations=[_MOCK_NOTE, *GENERIC_LIMITATIONS],
        )


class MockTextSourceSearch:
    name = "mock"

    async def search_text(self, text: str, *, phrases: list[str]) -> SearchResult:
        now = datetime.now(UTC)
        matches: list[SourceMatch] = []
        for phrase in phrases:
            if _bucket(phrase.encode("utf-8"), 2) == 0:
                continue  # deterministic "not found" for about half the phrases
            digest = hashlib.sha256(phrase.encode("utf-8")).hexdigest()[:10]
            matches.append(
                SourceMatch(
                    provider=self.name,
                    url=f"https://mock-source.example.invalid/articles/{digest}",
                    title="Mock phrase-search result",
                    snippet=f"…{phrase}…",
                    similarity=0.8,
                    source_kind="web_page",
                    matched_phrase=phrase,
                    published_at=None,
                    discovered_at=now,
                    raw={"mock": True},
                )
            )
        return SearchResult(
            provider=self.name,
            provider_version=MOCK_VERSION,
            modality="text",
            matches=matches,
            queried_phrases=list(phrases),
            latency_ms=0,
            estimated_cost=0.0,
            limitations=[_MOCK_NOTE, *GENERIC_LIMITATIONS],
        )
