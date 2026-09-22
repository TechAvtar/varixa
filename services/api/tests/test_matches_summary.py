"""T035: the Matches view gets a deterministic summary; every match stays a discovery signal."""

from types import SimpleNamespace as Row
from typing import Any

import pytest
from httpx import AsyncClient

from app.config import Settings
from app.services.search.summary import host_of, summarize_matches
from tests.test_image_upload import auth_headers, make_image


def m(
    url: str, kind: str = "web_page", sim: float | None = None, published: str | None = None
) -> Any:
    return Row(url=url, source_kind=kind, similarity=sim, published_at=published)


def test_host_normalisation() -> None:
    assert host_of("https://www.Example.com/a/b?x=1") == "example.com"
    assert host_of("https://cdn.example.org:8443/i.png") == "cdn.example.org"
    assert host_of("not a url") == ""


def test_summary_counts_domains_kinds_similarity_and_earliest_date() -> None:
    s = summarize_matches(
        [
            m("https://a.invalid/1", "web_page", 0.9, "2024-05-06"),
            m("https://www.a.invalid/2", "image", 0.4, None),
            m("https://b.invalid/3", "social", None, "2023-12-31T10:00:00Z"),
            m("https://c.invalid/4", "web_page", 0.7, "garbage date"),
        ]
    )
    assert s.match_count == 4 and s.domain_count == 3
    assert s.domains == ["a.invalid", "b.invalid", "c.invalid"]  # most frequent first, then name
    assert s.kinds == {"image": 1, "social": 1, "web_page": 2}
    assert (s.similarity_min, s.similarity_max) == (0.4, 0.9)
    assert s.dated_count == 3  # unparseable dates still count as "dated" but never as earliest
    assert s.earliest_published_at == "2023-12-31T10:00:00Z"
    assert s.earliest_published_url == "https://b.invalid/3"


def test_empty_summary() -> None:
    s = summarize_matches([])
    assert s.match_count == 0 and s.domains == [] and s.similarity_min is None
    assert s.earliest_published_at is None and s.kinds == {}


@pytest.fixture
def mock_search(migrated_settings: Settings) -> Settings:
    migrated_settings.source_search_provider = "mock"
    return migrated_settings


async def test_matches_endpoint_includes_summary(
    client: AsyncClient, mock_search: Settings
) -> None:
    headers = await auth_headers(client)
    r = await client.post(
        "/analysis/image",
        headers=headers,
        files={"file": ("a.jpg", make_image("JPEG", (64, 48)), "image/jpeg")},
    )
    body = (await client.get(f"/analysis/{r.json()['id']}/matches", headers=headers)).json()
    s = body["summary"]
    assert s["match_count"] == len(body["matches"]) and s["domain_count"] >= 1
    assert all(d.endswith(".invalid") for d in s["domains"])  # mock never points at real sites
    assert s["earliest_published_at"] is None and s["dated_count"] == 0
    assert s["similarity_min"] is not None and s["similarity_min"] <= s["similarity_max"]
    for match in body["matches"]:
        assert match["provider"] and match["discovered_at"] and match["url"]
