import uuid

import pytest
from httpx import AsyncClient

from app.config import Settings
from app.providers.search import (
    MockImageSourceSearch,
    MockTextSourceSearch,
    build_image_source_search,
    build_text_source_search,
)
from app.services.text.phrases import select_distinctive_phrases
from tests.test_image_upload import auth_headers, make_image
from tests.test_text import ENGLISH

LONG_TEXT = (
    "Dear colleagues, thank you for coming. "
    "The photovoltaic installation exceeded its projected quarterly generation by eleven "
    "percent despite unusually overcast conditions across the northern facility. "
    "It was fine. "
    "Maintenance crews recalibrated the inverter firmware after detecting intermittent "
    "voltage irregularities on the secondary array. "
    "The photovoltaic installation exceeded its projected quarterly generation by eleven "
    "percent despite unusually overcast conditions across the northern facility."
)


# -- phrase selection -----------------------------------------------------------------------


def test_phrase_selection_prefers_distinctive_sentences_and_dedupes() -> None:
    phrases = select_distinctive_phrases(LONG_TEXT, max_phrases=5)
    assert 1 <= len(phrases) <= 5
    assert all(len(p.split()) <= 10 for p in phrases)
    assert phrases[0].startswith("The photovoltaic installation") or phrases[0].startswith(
        "Maintenance crews"
    )
    assert not any(p.lower().startswith("dear colleagues") for p in phrases)  # boilerplate
    assert not any(p.lower().startswith("it was fine") for p in phrases)  # too short
    assert len({p.lower() for p in phrases}) == len(phrases)  # duplicate sentence collapsed


def test_phrase_selection_is_deterministic_and_bounded() -> None:
    assert select_distinctive_phrases(ENGLISH) == select_distinctive_phrases(ENGLISH)
    assert select_distinctive_phrases("too short", max_phrases=3) == []
    assert len(select_distinctive_phrases(LONG_TEXT, max_phrases=1)) == 1


# -- mock providers ----------------------------------------------------------------------------


async def test_mock_image_search_is_deterministic_and_self_declared() -> None:
    provider = MockImageSourceSearch()
    a = await provider.search_image(b"image bytes", metadata={})
    b = await provider.search_image(b"image bytes", metadata={})
    assert [m.url for m in a.matches] == [m.url for m in b.matches]
    assert a.provider == "mock" and a.modality == "image"
    assert all(m.url.endswith(m.url.split("/")[-1]) and ".invalid/" in m.url for m in a.matches)
    assert any("MOCK" in x for x in a.limitations)


async def test_mock_text_search_queries_given_phrases() -> None:
    provider = MockTextSourceSearch()
    r = await provider.search_text("whatever", phrases=["alpha beta gamma", "delta epsilon"])
    assert r.queried_phrases == ["alpha beta gamma", "delta epsilon"]
    assert all(m.matched_phrase in r.queried_phrases for m in r.matches)
    assert r.modality == "text"


def test_build_search_respects_setting(migrated_settings: Settings) -> None:
    migrated_settings.source_search_provider = "none"
    assert build_image_source_search(migrated_settings) is None
    assert build_text_source_search(migrated_settings) is None
    migrated_settings.source_search_provider = "mock"
    assert build_image_source_search(migrated_settings) is not None
    assert build_text_source_search(migrated_settings) is not None


# -- step + API -----------------------------------------------------------------------------------


async def test_no_provider_skips_search_and_matches_is_404(client: AsyncClient) -> None:
    headers = await auth_headers(client)
    r = await client.post("/analysis/text", headers=headers, json={"text": LONG_TEXT})
    aid = r.json()["id"]
    detail = (await client.get(f"/analysis/{aid}", headers=headers)).json()
    step = next(s for s in detail["steps"] if s["name"] == "search")
    assert step["status"] == "skipped"
    assert detail["status"] == "completed"
    assert (await client.get(f"/analysis/{aid}/matches", headers=headers)).status_code == 404


@pytest.fixture
def mock_search(migrated_settings: Settings) -> Settings:
    migrated_settings.source_search_provider = "mock"
    return migrated_settings


async def test_mock_search_persists_matches_for_text_and_image(
    client: AsyncClient, mock_search: Settings
) -> None:
    headers = await auth_headers(client)
    txt = await client.post("/analysis/text", headers=headers, json={"text": LONG_TEXT})
    img = await client.post(
        "/analysis/image",
        headers=headers,
        files={"file": ("a.png", make_image("PNG"), "image/png")},
    )
    for created, modality in ((txt, "text"), (img, "image")):
        aid = created.json()["id"]
        detail = (await client.get(f"/analysis/{aid}", headers=headers)).json()
        step = next(s for s in detail["steps"] if s["name"] == "search")
        assert step["status"] == "completed" and step["details"]["provider"] == "mock"

        r = await client.get(f"/analysis/{aid}/matches", headers=headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["modality"] == modality and body["provider"] == "mock"
        assert isinstance(body["matches"], list) and body["searched_at"]
        assert any("MOCK" in x for x in body["limitations"])
        assert any("not where it originated" in x for x in body["limitations"])
        if modality == "text":
            assert body["queried_phrases"] and all(
                len(p.split()) <= 10 for p in body["queried_phrases"]
            )
            for m in body["matches"]:
                assert m["matched_phrase"] in body["queried_phrases"]
                assert ".invalid/" in m["url"]
        for i, m in enumerate(body["matches"]):
            assert m["rank"] == i + 1


async def test_search_is_idempotent_on_rerun(client: AsyncClient, mock_search: Settings) -> None:
    from sqlalchemy import select

    from app.config import get_settings
    from app.models import Analysis
    from app.services.analysis.pipeline import PipelineContext
    from app.services.analysis.search_step import SourceSearchStep
    from app.services.analysis.text_steps import LoadAndNormalizeTextStep

    headers = await auth_headers(client)
    r = await client.post("/analysis/text", headers=headers, json={"text": LONG_TEXT})
    aid = uuid.UUID(r.json()["id"])
    before = (await client.get(f"/analysis/{aid}/matches", headers=headers)).json()

    app = client._transport.app  # type: ignore[attr-defined]
    settings = app.dependency_overrides[get_settings]()
    async with app.state.session_factory() as db:
        analysis = (await db.execute(select(Analysis).where(Analysis.id == aid))).scalar_one()
        await db.refresh(analysis, ["files"])
        ctx = PipelineContext(
            analysis=analysis,
            file=analysis.files[0],
            session=db,
            storage=app.state.storage,
            settings=settings,
        )
        await LoadAndNormalizeTextStep().run(ctx)
        await SourceSearchStep().run(ctx)
        await db.commit()

    after = (await client.get(f"/analysis/{aid}/matches", headers=headers)).json()
    assert [m["url"] for m in after["matches"]] == [m["url"] for m in before["matches"]]


async def test_matches_endpoint_enforces_ownership(
    client: AsyncClient, mock_search: Settings
) -> None:
    owner = await auth_headers(client, "o@example.com")
    r = await client.post("/analysis/text", headers=owner, json={"text": LONG_TEXT})
    aid = r.json()["id"]
    intruder = await auth_headers(client, "i@example.com")
    assert (await client.get(f"/analysis/{aid}/matches", headers=intruder)).status_code == 404
    assert (await client.get(f"/analysis/{uuid.uuid4()}/matches", headers=owner)).status_code == 404
    assert (await client.get(f"/analysis/{aid}/matches")).status_code == 401
