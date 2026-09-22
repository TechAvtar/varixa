"""Deterministic summary of a source-search run for the Matches view. Pure; no I/O."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from app.utils.timeparse import as_utc, parse_timestamp

MAX_DOMAINS = 20


@dataclass(frozen=True)
class MatchesSummary:
    match_count: int
    domains: list[str] = field(default_factory=list)  # distinct hosts, most frequent first
    domain_count: int = 0
    kinds: dict[str, int] = field(default_factory=dict)
    similarity_min: float | None = None
    similarity_max: float | None = None
    dated_count: int = 0
    # As reported by the providers; never a statement about when the content was created.
    earliest_published_at: str | None = None
    earliest_published_url: str | None = None


def host_of(url: str) -> str:
    try:
        host = urlsplit(url).hostname or ""
    except ValueError:
        return ""
    return host.lower().removeprefix("www.")


def summarize_matches(matches: Sequence[Any]) -> MatchesSummary:
    counts: dict[str, int] = {}
    kinds: dict[str, int] = {}
    sims: list[float] = []
    dated = 0
    earliest: tuple[datetime, str, str] | None = None
    for m in matches:
        host = host_of(str(m.url))
        if host:
            counts[host] = counts.get(host, 0) + 1
        kind = str(m.source_kind or "unknown")
        kinds[kind] = kinds.get(kind, 0) + 1
        if m.similarity is not None:
            sims.append(float(m.similarity))
        if m.published_at:
            dated += 1
            dt, _ = parse_timestamp(m.published_at)
            if dt is not None and (earliest is None or as_utc(dt) < as_utc(earliest[0])):
                earliest = (dt, str(m.published_at), str(m.url))
    domains = [h for h, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]
    return MatchesSummary(
        match_count=len(matches),
        domains=domains[:MAX_DOMAINS],
        domain_count=len(domains),
        kinds=dict(sorted(kinds.items())),
        similarity_min=min(sims) if sims else None,
        similarity_max=max(sims) if sims else None,
        dated_count=dated,
        earliest_published_at=earliest[1] if earliest else None,
        earliest_published_url=earliest[2] if earliest else None,
    )
