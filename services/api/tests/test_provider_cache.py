from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.provider_cache import ProviderCacheEntry
from app.providers.ai.base import DetectionResult
from app.providers.ai.cache import (
    CachedAIDetector,
    deserialize_detection,
    serialize_detection,
)
from app.providers.cache import InMemoryProviderCache, cache_key, content_hash
from app.providers.search.base import SearchResult, SourceMatch
from app.providers.search.cache import (
    CachedTextSourceSearch,
    deserialize_search,
    serialize_search,
)
from app.repositories.provider_cache import DbProviderCache
from tests.test_image_upload import auth_headers, make_image
from tests.test_text import ENGLISH

TTL = timedelta(hours=1)


# -- keys ----------------------------------------


def test_cache_key_changes_with_every_component() -> None:
    base = dict(provider="p", operation="op", model_version="m@1", content_hash="c")
    k = cache_key(**base)
    assert k != cache_key(**{**base, "provider": "q"})
    assert k != cache_key(**{**base, "operation": "op2"})
    assert k != cache_key(**{**base, "model_version": "m@2"})
    assert k != cache_key(**{**base, "content_hash": "d"})
    assert content_hash(b"x") == content_hash("x") and len(k) == 64


# -- DB cache ----------------------------------------


async def test_db_cache_set_get_hit_count_and_expiry(session: AsyncSession) -> None:
    cache = DbProviderCache(session, ttl=TTL)
    key = cache_key(provider="p", operation="op", model_version="m", content_hash="c")
    assert await cache.get(key) is None
    await cache.set(
        key, {"a": 1}, provider="p", operation="op", model_version="m", content_hash="c"
    )
    hit1 = await cache.get(key)
    hit2 = await cache.get(key)
    assert hit1 is not None and hit1.payload == {"a": 1} and hit1.hit_count == 1
    assert hit2 is not None and hit2.hit_count == 2
    await session.commit()

    row = (await session.execute(select(ProviderCacheEntry))).scalar_one()
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await session.commit()
    assert await cache.get(key) is None  # expired entries are invisible
    assert await cache.purge_expired() == 1


async def test_db_cache_set_replaces_existing(session: AsyncSession) -> None:
    cache = DbProviderCache(session, ttl=TTL)
    key = cache_key(provider="p", operation="op", model_version="m", content_hash="c")
    await cache.set(
        key, {"v": 1}, provider="p", operation="op", model_version="m", content_hash="c"
    )
    await cache.set(
        key, {"v": 2}, provider="p", operation="op", model_version="m", content_hash="c"
    )
    await session.commit()
    rows = (await session.execute(select(ProviderCacheEntry))).scalars().all()
    assert len(rows) == 1 and rows[0].payload_json == {"v": 2}


async def test_in_memory_cache_honours_ttl() -> None:
    cache = InMemoryProviderCache(ttl=timedelta(seconds=0))
    await cache.set("k", {"x": 1}, provider="p", operation="o", model_version="m", content_hash="c")
    assert await cache.get("k") is None


# -- serialisation round trips ----------------------------------------


def test_detection_round_trip() -> None:
    original = DetectionResult(
        provider="p",
        model="m",
        model_version="1",
        modality="text",
        score=0.42,
        label="likely_human",
        calibrated=False,
        raw={"k": [1, 2]},
        latency_ms=12,
        request_id="r",
        cached=True,
        estimated_cost=0.001,
        limitations=["a"],
    )
    back = deserialize_detection(serialize_detection(original))
    assert back == DetectionResult(**{**original.__dict__, "cached": False})


def test_search_round_trip_preserves_matches_and_times() -> None:
    now = datetime(2026, 9, 22, 10, 0, tzinfo=UTC)
    original = SearchResult(
        provider="p",
        provider_version="2",
        modality="text",
        matches=[
            SourceMatch(
                provider="p",
                url="https://x.invalid/a",
                title="t",
                snippet="s",
                similarity=0.5,
                source_kind="web_page",
                matched_phrase="ph",
                published_at="2020-01-01",
                discovered_at=now,
                raw={"z": 1},
            )
        ],
        queried_phrases=["ph"],
        latency_ms=5,
        request_id=None,
        cached=True,
        estimated_cost=0.0,
        limitations=["l"],
    )
    back = deserialize_search(serialize_search(original))
    assert back.matches[0] == original.matches[0]
    assert back.queried_phrases == ["ph"] and back.cached is False


# -- wrappers ----------------------------------------


class CountingDetector:
    name = "counting"
    modalities = frozenset({"text"})
    calls = 0

    async def detect(self, content: Any, *, modality: Any, metadata: Any) -> DetectionResult:
        self.calls += 1
        return DetectionResult(
            provider="counting",
            model="m",
            model_version="1",
            modality=modality,
            score=0.3,
            label="likely_human",
            calibrated=False,
            latency_ms=7,
            estimated_cost=0.01,
        )


async def test_cached_detector_uses_db_cache_across_sessions(
    session: AsyncSession, migrated_settings: Settings
) -> None:
    inner = CountingDetector()
    det = CachedAIDetector(inner, DbProviderCache(session, ttl=TTL), model_hint="m")
    first = await det.detect("hello", modality="text", metadata={})
    await session.commit()
    second = await det.detect("hello", modality="text", metadata={})
    assert inner.calls == 1
    assert not first.cached and second.cached
    assert second.estimated_cost == 0.0 and second.latency_ms == 0 and second.score == 0.3
    row = (await session.execute(select(ProviderCacheEntry))).scalar_one()
    assert row.provider == "counting" and row.operation == "ai.detect:text"
    assert row.model_version == "m@1" and row.hit_count == 1


class CountingTextSearch:
    name = "counting"
    calls = 0

    async def search_text(self, text: str, *, phrases: list[str]) -> SearchResult:
        self.calls += 1
        return SearchResult(
            provider="counting",
            provider_version="1",
            modality="text",
            matches=[],
            queried_phrases=phrases,
            latency_ms=3,
            estimated_cost=0.02,
        )


async def test_cached_text_search_keys_on_phrases(session: AsyncSession) -> None:
    inner = CountingTextSearch()
    s = CachedTextSourceSearch(inner, DbProviderCache(session, ttl=TTL))
    a = await s.search_text("doc A", phrases=["x y z"])
    b = await s.search_text("doc B (different text, same phrases)", phrases=["x y z"])
    c = await s.search_text("doc A", phrases=["other"])
    assert inner.calls == 2 and not a.cached and b.cached and not c.cached


# -- end to end ----------------------------------------


@pytest.fixture
def mock_providers(migrated_settings: Settings) -> Settings:
    migrated_settings.ai_detector_provider = "mock"
    migrated_settings.source_search_provider = "mock"
    return migrated_settings


async def test_second_analysis_of_same_content_is_served_from_persistent_cache(
    client: AsyncClient, mock_providers: Settings
) -> None:
    headers = await auth_headers(client)
    data = make_image("JPEG", (23, 29))
    await client.post(
        "/analysis/image", headers=headers, files={"file": ("a.jpg", data, "image/jpeg")}
    )
    second = await client.post(
        "/analysis/image", headers=headers, files={"file": ("b.jpg", data, "image/jpeg")}
    )
    calls = (
        await client.get(f"/analysis/{second.json()['id']}/provider-calls", headers=headers)
    ).json()["calls"]
    statuses = {c["operation"]: c["status"] for c in calls}
    assert statuses["ai.detect"] == "cached" and statuses["search.image"] == "cached"

    app = client._transport.app  # type: ignore[attr-defined]
    async with app.state.session_factory() as db:
        rows = (await db.execute(select(ProviderCacheEntry))).scalars().all()
    ops = {r.operation for r in rows}
    assert "ai.detect:image" in ops and "search.image" in ops
    assert all(r.hit_count == 1 for r in rows if r.operation in ops)


async def test_cache_is_shared_across_users_but_never_leaks_identity(
    client: AsyncClient, mock_providers: Settings
) -> None:
    alice = await auth_headers(client, "alice@example.com")
    bob = await auth_headers(client, "bob@example.com")
    await client.post("/analysis/text", headers=alice, json={"text": ENGLISH})
    r = await client.post("/analysis/text", headers=bob, json={"text": ENGLISH})
    calls = (await client.get(f"/analysis/{r.json()['id']}/provider-calls", headers=bob)).json()
    assert next(c for c in calls["calls"] if c["operation"] == "ai.detect")["status"] == "cached"
    app = client._transport.app  # type: ignore[attr-defined]
    async with app.state.session_factory() as db:
        rows = (await db.execute(select(ProviderCacheEntry))).scalars().all()
    for row in rows:
        blob = str(row.payload_json)
        assert "alice" not in blob and "bob" not in blob
