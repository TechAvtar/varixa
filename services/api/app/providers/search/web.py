"""Real text source search: Wikipedia, OpenAlex and a self-hosted SearXNG, behind one adapter.

Each distinctive phrase is searched as an exact (quoted) phrase on every enabled backend and the
hits are merged by URL. A backend that fails does not sink the others; the result is marked
incomplete (and so never cached) and the limitation says how many queries failed. If every
query fails the search raises, so a broken setup is never reported as "no matches".

Privacy: the short phrases (never the whole text) are sent to the enabled services. Endpoints
come from configuration and are checked against the outbound allowlist when settings load;
URLs that backends *return* are only stored as links.
"""

import asyncio
import html
import re
import time
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import quote

import httpx

from app.providers.search.base import (
    GENERIC_LIMITATIONS,
    SearchResult,
    SourceMatch,
    SourceSearchError,
)

USER_AGENT = "Verixa/0.1 (content forensics; phrase search)"
MAX_CONCURRENCY = 4
_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")


def _plain(text: str) -> str:
    return _SPACE.sub(" ", html.unescape(_TAG.sub("", text))).strip()


def _norm(text: str) -> str:
    return _SPACE.sub(" ", text).strip().casefold()


def _quoted(phrase: str) -> str:
    return '"' + phrase.replace('"', " ").strip() + '"'


def _verbatim(phrase: str, *texts: str | None) -> bool:
    needle = _norm(phrase)
    return any(t and needle in _norm(t) for t in texts)


class TextBackend(Protocol):
    name: str

    async def query(
        self, client: httpx.AsyncClient, phrase: str, *, limit: int, now: datetime
    ) -> list[SourceMatch]: ...


class WikipediaBackend:
    name = "wikipedia"

    def __init__(self, language: str) -> None:
        self._host = f"{language}.wikipedia.org"

    async def query(
        self, client: httpx.AsyncClient, phrase: str, *, limit: int, now: datetime
    ) -> list[SourceMatch]:
        resp = await client.get(
            f"https://{self._host}/w/api.php",
            params={
                "action": "query",
                "list": "search",
                "srsearch": _quoted(phrase),
                "srlimit": limit,
                "srprop": "snippet|timestamp",
                "format": "json",
            },
        )
        resp.raise_for_status()
        out: list[SourceMatch] = []
        for item in (resp.json().get("query") or {}).get("search") or []:
            title = str(item.get("title") or "")
            if not title:
                continue
            snippet = _plain(str(item.get("snippet") or ""))
            out.append(
                SourceMatch(
                    provider=self.name,
                    url=f"https://{self._host}/wiki/{quote(title.replace(' ', '_'))}",
                    title=title,
                    snippet=snippet or None,
                    similarity=1.0 if _verbatim(phrase, snippet) else None,
                    source_kind="web_page",
                    matched_phrase=phrase,
                    # The timestamp is the page's last edit, not a publication date.
                    published_at=None,
                    discovered_at=now,
                    raw={"last_edited": item.get("timestamp"), "pageid": item.get("pageid")},
                )
            )
        return out


class OpenAlexBackend:
    name = "openalex"

    async def query(
        self, client: httpx.AsyncClient, phrase: str, *, limit: int, now: datetime
    ) -> list[SourceMatch]:
        resp = await client.get(
            "https://api.openalex.org/works",
            params={
                "search": _quoted(phrase),
                "per-page": limit,
                "select": "id,display_name,doi,publication_date,primary_location,type",
            },
        )
        resp.raise_for_status()
        out: list[SourceMatch] = []
        for item in resp.json().get("results") or []:
            location = item.get("primary_location") or {}
            url = location.get("landing_page_url") or item.get("doi") or item.get("id")
            if not url:
                continue
            out.append(
                SourceMatch(
                    provider=self.name,
                    url=str(url),
                    title=(str(item["display_name"]) if item.get("display_name") else None),
                    snippet=None,
                    similarity=None,  # a full-text hit; no snippet to confirm the wording
                    source_kind="document",
                    matched_phrase=phrase,
                    published_at=item.get("publication_date"),
                    discovered_at=now,
                    raw={"openalex_id": item.get("id"), "type": item.get("type")},
                )
            )
        return out


class SearxngBackend:
    name = "searxng"

    def __init__(self, base_url: str) -> None:
        self._base = base_url.rstrip("/")

    async def query(
        self, client: httpx.AsyncClient, phrase: str, *, limit: int, now: datetime
    ) -> list[SourceMatch]:
        resp = await client.get(
            f"{self._base}/search",
            params={"q": _quoted(phrase), "format": "json", "safesearch": 0},
        )
        resp.raise_for_status()
        try:
            results = resp.json().get("results") or []
        except ValueError as exc:
            raise SourceSearchError(
                "SearXNG did not return JSON (enable the json format in its settings)"
            ) from exc
        out: list[SourceMatch] = []
        for item in results[:limit]:
            url = item.get("url")
            if not url:
                continue
            snippet = _plain(str(item.get("content") or ""))
            title = str(item.get("title") or "") or None
            out.append(
                SourceMatch(
                    provider=self.name,
                    url=str(url),
                    title=title,
                    snippet=snippet or None,
                    similarity=1.0 if _verbatim(phrase, snippet, title) else None,
                    source_kind="web_page",
                    matched_phrase=phrase,
                    published_at=None,  # engines report dates inconsistently; kept in raw only
                    discovered_at=now,
                    raw={"engines": item.get("engines") or [item.get("engine")]},
                )
            )
        return out


class WebTextSourceSearch:
    """Phrase search across the enabled backends, merged and de-duplicated by URL."""

    name = "web"

    def __init__(
        self,
        backends: list[TextBackend],
        *,
        results_per_phrase: int,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not backends:
            raise SourceSearchError("no text search backend is enabled")
        self._backends = backends
        self._limit = results_per_phrase
        self._timeout = timeout_seconds
        self._transport = transport
        self.version = "+".join(b.name for b in backends)
        # Part of the result-cache key: a different backend set is a different search.
        self.cache_scope = self.version

    async def search_text(self, text: str, *, phrases: list[str]) -> SearchResult:
        started = time.perf_counter()
        now = datetime.now(UTC)
        gate = asyncio.Semaphore(MAX_CONCURRENCY)
        failures: list[str] = []

        async with httpx.AsyncClient(
            timeout=self._timeout,
            transport=self._transport,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            follow_redirects=False,
        ) as client:

            async def one(backend: TextBackend, phrase: str) -> list[SourceMatch]:
                async with gate:
                    try:
                        return await backend.query(client, phrase, limit=self._limit, now=now)
                    except httpx.TimeoutException:
                        failures.append(f"{backend.name}: timed out")
                    except httpx.HTTPStatusError as exc:
                        failures.append(f"{backend.name}: HTTP {exc.response.status_code}")
                    except (httpx.HTTPError, ValueError, SourceSearchError) as exc:
                        failures.append(f"{backend.name}: {exc.__class__.__name__}")
                    return []

            jobs = [(b, p) for p in phrases for b in self._backends]
            batches = await asyncio.gather(*(one(b, p) for b, p in jobs))

        if jobs and len(failures) == len(jobs):
            kinds = sorted(set(failures))[:4]
            raise SourceSearchError("every search query failed (" + "; ".join(kinds) + ")")

        merged: dict[str, SourceMatch] = {}
        for batch in batches:
            for m in batch:
                merged.setdefault(m.url, m)
        limitations = [
            "Short phrases from the text were sent to these public services: "
            + ", ".join(b.name for b in self._backends)
            + ". Hits are exact-phrase results in each service's own index.",
            *GENERIC_LIMITATIONS,
        ]
        complete = not failures
        if failures:
            limitations.insert(
                0,
                f"{len(failures)} of {len(jobs)} queries failed, so this result may be missing "
                "matches (" + "; ".join(sorted(set(failures))[:4]) + ").",
            )
        return SearchResult(
            provider=self.name,
            provider_version=self.version,
            modality="text",
            matches=list(merged.values()),
            queried_phrases=list(phrases),
            latency_ms=int((time.perf_counter() - started) * 1000),
            estimated_cost=0.0,
            limitations=limitations,
            complete=complete,
        )
