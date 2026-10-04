"""Local open-source detectors and real web search adapters (no network, no model needed).

The detector runtime is faked and HTTP is served by ``httpx.MockTransport``; the tests that run
real models skip themselves when the optional ML libraries or fetched models are absent.
"""

import base64
import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from pydantic import ValidationError

import app.providers.ai as ai_package
from app.config import Settings
from app.providers.ai import AIDetectorError, AIDetectorUnavailableError, build_ai_detector
from app.providers.ai.local import (
    ClassifierRuntime,
    LocalAIDetector,
    Scored,
    TransformersRuntime,
    model_revision,
    model_slug,
)
from app.providers.cache import InMemoryProviderCache
from app.providers.search import (
    CachedTextSourceSearch,
    GoogleVisionImageSearch,
    OpenAlexBackend,
    SearxngBackend,
    SourceSearchError,
    WebTextSourceSearch,
    WikipediaBackend,
    build_image_source_search,
    build_text_source_search,
)
from tests.test_image_upload import auth_headers, make_image
from tests.test_text import ENGLISH

# -- local detector -------------------------------------------------------------------------


class FakeRuntime(ClassifierRuntime):
    def __init__(
        self,
        *,
        image: Scored | Exception | None = None,
        text: Scored | Exception | None = None,
    ) -> None:
        self._image = image if image is not None else Scored({"artificial": 0.9, "human": 0.1})
        self._text = text
        self.image_calls = 0
        self.text_calls = 0

    def image_model_info(self) -> tuple[str, str]:
        return "org/image-model", "abc123abc123"

    def text_model_info(self) -> tuple[str, str]:
        return "org/text-model", "def456def456"

    def classify_image(self, data: bytes) -> Scored:
        self.image_calls += 1
        if isinstance(self._image, Exception):
            raise self._image
        return self._image

    def classify_text(self, text: str) -> Scored | None:
        self.text_calls += 1
        if isinstance(self._text, Exception):
            raise self._text
        return self._text


def make_detector(runtime: ClassifierRuntime, **kwargs: Any) -> LocalAIDetector:
    return LocalAIDetector(
        runtime,
        image_ai_label=kwargs.pop("image_ai_label", "artificial"),
        text_ai_label=kwargs.pop("text_ai_label", "Fake"),
        high=0.85,
        medium=0.6,
        timeout_seconds=kwargs.pop("timeout_seconds", 5.0),
    )


async def test_local_image_result_is_an_uncalibrated_labelled_signal() -> None:
    result = await make_detector(FakeRuntime()).detect(b"img", modality="image", metadata={})
    assert result.provider == "local" and result.modality == "image"
    assert (result.model, result.model_version) == ("org/image-model", "abc123abc123")
    assert result.score == 0.9 and result.label == "likely_ai" and not result.calibrated
    assert result.estimated_cost == 0.0
    assert result.raw["probabilities"] == {"artificial": 0.9, "human": 0.1}
    assert any("open-source image classifier" in x for x in result.limitations)
    assert any("not evidence of who created" in x for x in result.limitations)


async def test_local_text_result_uses_the_text_model_and_label() -> None:
    runtime = FakeRuntime(text=Scored({"Real": 0.7, "Fake": 0.3}, units=2, tokens=900))
    result = await make_detector(runtime).detect("some text", modality="text", metadata={})
    assert result.model == "org/text-model" and result.score == 0.3
    assert result.label == "likely_human"
    assert result.raw["windows"] == 2 and result.raw["tokens"] == 900
    assert any("GPT-2 era" in x for x in result.limitations)


async def test_too_short_text_gives_no_score_instead_of_a_guess() -> None:
    result = await make_detector(FakeRuntime(text=None)).detect("hi", modality="text", metadata={})
    assert result.score is None and result.label == "unavailable"
    assert result.raw == {"reason": "too_short"}
    assert any("too short" in x for x in result.limitations)


async def test_unknown_ai_label_is_a_configuration_error() -> None:
    det = make_detector(FakeRuntime(), image_ai_label="synthetic")
    with pytest.raises(AIDetectorUnavailableError, match="synthetic"):
        await det.detect(b"img", modality="image", metadata={})


async def test_runtime_failures_never_leak_internals() -> None:
    runtime = FakeRuntime(image=RuntimeError("CUDA tensor /secret/path blew up"))
    with pytest.raises(AIDetectorError) as err:
        await make_detector(runtime).detect(b"img", modality="image", metadata={})
    assert "RuntimeError" in str(err.value) and "/secret/path" not in str(err.value)


async def test_slow_inference_times_out() -> None:
    import time

    class Slow(FakeRuntime):
        def classify_image(self, data: bytes) -> Scored:
            time.sleep(0.5)
            return Scored({"artificial": 0.1})

    with pytest.raises(AIDetectorError, match="timed out"):
        await make_detector(Slow(), timeout_seconds=0.05).detect(
            b"img", modality="image", metadata={}
        )


def test_model_slug_and_revision(tmp_path: Path) -> None:
    assert model_slug("org/name") == "org--name"
    assert model_revision(tmp_path) == "unknown"
    (tmp_path / "verixa-model.json").write_text(json.dumps({"revision": "0123456789abcdef"}))
    assert model_revision(tmp_path) == "0123456789ab"
    (tmp_path / "verixa-model.json").write_text("not json")
    assert model_revision(tmp_path) == "unknown"


async def test_missing_model_files_say_how_to_fetch_them(tmp_path: Path) -> None:
    pytest.importorskip("torch")
    pytest.importorskip("transformers")
    runtime = TransformersRuntime(
        model_dir=tmp_path,
        image_model="org/image",
        image_ai_label="artificial",
        text_model="org/text",
        text_ai_label="Fake",
        text_min_tokens=50,
        text_max_chunks=8,
    )
    det = make_detector(runtime)
    with pytest.raises(AIDetectorUnavailableError, match="fetch_detector_models"):
        await det.detect(b"img", modality="image", metadata={})


def test_builder_returns_cached_local_detector_with_one_shared_runtime(
    settings: Settings,
) -> None:
    settings.ai_detector_provider = "local"
    first = build_ai_detector(settings)
    second = build_ai_detector(settings)
    assert first is not None and second is not None
    assert first.name == "local" and first.modalities == frozenset({"image", "text"})
    runtimes = [
        r for k, r in ai_package._local_runtimes.items() if k[0] == settings.detector_model_dir
    ]
    assert len(runtimes) == 1  # not rebuilt (and so not reloaded) for every analysis


async def test_pipeline_runs_the_local_detector_end_to_end(
    client: AsyncClient, migrated_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = FakeRuntime(text=Scored({"Real": 0.2, "Fake": 0.8}, units=1, tokens=300))
    monkeypatch.setattr(ai_package, "_local_runtime", lambda settings: runtime)
    migrated_settings.ai_detector_provider = "local"
    headers = await auth_headers(client)

    image = await client.post(
        "/analysis/image",
        headers=headers,
        files={"file": ("a.png", make_image("PNG"), "image/png")},
    )
    text = await client.post("/analysis/text", headers=headers, json={"text": ENGLISH * 3})
    assert runtime.image_calls == 1 and runtime.text_calls == 1
    for created, expected in ((image, 0.9), (text, 0.8)):
        aid = created.json()["id"]
        detail = (await client.get(f"/analysis/{aid}", headers=headers)).json()
        step = next(s for s in detail["steps"] if s["name"] == "ai")
        assert step["status"] == "completed" and step["details"]["provider"] == "local"
        ev = (await client.get(f"/analysis/{aid}/evidence", headers=headers)).json()
        signal = next(i for i in ev["items"] if i["rule"] == "ai.signal")
        # Uncalibrated, so a high score is capped at POSSIBLE whatever the model says.
        assert signal["level"] == "POSSIBLE" and signal["data"]["score"] == expected
        assert signal["data"]["calibrated"] is False


# -- real models (skipped unless the ml extra and the fetched models are present) --------------

_MODELS = Path("data/models")


def _have(repo: str) -> bool:
    return (_MODELS / model_slug(repo) / "config.json").is_file()


@pytest.mark.skipif(
    not (_have("haywoodsloan/ai-image-detector-deploy")), reason="image model not fetched"
)
async def test_real_image_model_scores_a_picture() -> None:
    pytest.importorskip("torch")
    pytest.importorskip("transformers")
    s = Settings(_env_file=None, ai_detector_provider="local", ai_detector_model_dir=_MODELS)
    det = ai_package.build_ai_detector(s, cache=InMemoryProviderCache(ttl=timedelta(0)))
    assert det is not None
    result = await det.detect(make_image("PNG", size=(256, 256)), modality="image", metadata={})
    assert result.score is not None and 0.0 <= result.score <= 1.0
    assert set(result.raw["probabilities"]) >= {"artificial", "real"}
    assert result.model_version != "unknown"


@pytest.mark.skipif(
    not (_have("openai-community/roberta-base-openai-detector")), reason="text model not fetched"
)
async def test_real_text_model_scores_text_and_declines_short_text() -> None:
    pytest.importorskip("torch")
    pytest.importorskip("transformers")
    s = Settings(_env_file=None, ai_detector_provider="local", ai_detector_model_dir=_MODELS)
    det = ai_package.build_ai_detector(s, cache=InMemoryProviderCache(ttl=timedelta(0)))
    assert det is not None
    long = await det.detect(ENGLISH * 4, modality="text", metadata={})
    assert long.score is not None and 0.0 <= long.score <= 1.0 and long.raw["windows"] >= 1
    short = await det.detect("Too short.", modality="text", metadata={})
    assert short.score is None and short.label == "unavailable"


# -- real search: Wikipedia, OpenAlex, SearXNG -------------------------------------------------

PHRASE = "the quick brown fox jumps over the lazy dog"


def web_handler(seen: list[httpx.Request], *, openalex_status: int = 200) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        host = request.url.host
        if host == "en.wikipedia.org":
            return httpx.Response(
                200,
                json={
                    "query": {
                        "search": [
                            {
                                "title": "Pangram (test)",
                                "pageid": 7,
                                "timestamp": "2026-09-01T00:00:00Z",
                                "snippet": '&quot;The <span class="searchmatch">quick</span> '
                                "brown fox jumps over the lazy dog&quot; is a pangram",
                            },
                            {"title": "Other page", "pageid": 8, "snippet": "unrelated words"},
                        ]
                    }
                },
            )
        if host == "api.openalex.org":
            if openalex_status != 200:
                return httpx.Response(openalex_status, json={})
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "id": "https://openalex.org/W1",
                            "display_name": "A paper",
                            "publication_date": "2020-02-03",
                            "type": "article",
                            "primary_location": {"landing_page_url": "https://journal.example/p"},
                        },
                        {"id": "https://openalex.org/W2", "doi": "javascript:alert(1)"},
                    ]
                },
            )
        if host == "localhost":
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "url": "https://news.example/a",
                            "title": "News",
                            "content": f"... {PHRASE.upper()} ...",
                            "engines": ["duckduckgo"],
                            "publishedDate": "2019-01-01",
                        },
                        {"url": "https://blog.example/b", "title": "Blog", "content": "other"},
                    ]
                },
            )
        return httpx.Response(404)

    return handler


def web_search(
    backends: list[Any], seen: list[httpx.Request], **kwargs: Any
) -> WebTextSourceSearch:
    return WebTextSourceSearch(
        backends,
        results_per_phrase=5,
        timeout_seconds=5,
        transport=httpx.MockTransport(web_handler(seen, **kwargs)),
    )


async def test_web_search_merges_backends_and_marks_what_it_can_confirm() -> None:
    seen: list[httpx.Request] = []
    search = web_search(
        [WikipediaBackend("en"), OpenAlexBackend(), SearxngBackend("http://localhost:8888")], seen
    )
    result = await search.search_text("whole text", phrases=[PHRASE])
    assert result.provider == "web" and result.provider_version == "wikipedia+openalex+searxng"
    assert result.complete and result.queried_phrases == [PHRASE]
    by_url = {m.url: m for m in result.matches}

    wiki = by_url["https://en.wikipedia.org/wiki/Pangram_%28test%29"]
    assert wiki.similarity == 1.0 and wiki.matched_phrase == PHRASE
    assert wiki.published_at is None  # the API reports the last edit, which is not publication
    assert wiki.raw["last_edited"] == "2026-09-01T00:00:00Z"
    assert by_url["https://en.wikipedia.org/wiki/Other_page"].similarity is None

    paper = by_url["https://journal.example/p"]
    assert paper.source_kind == "document" and paper.published_at == "2020-02-03"
    assert paper.similarity is None

    news = by_url["https://news.example/a"]
    assert news.similarity == 1.0 and news.published_at is None  # case-insensitive verbatim check
    assert news.raw["engines"] == ["duckduckgo"]

    # Every backend was asked for the exact phrase, in quotes.
    queries = {
        r.url.params.get("srsearch") or r.url.params.get("search") or r.url.params["q"]
        for r in seen
    }
    assert queries == {f'"{PHRASE}"'}
    assert any("sent to these public services" in x for x in result.limitations)


async def test_one_failing_backend_gives_an_incomplete_result_that_is_not_cached() -> None:
    seen: list[httpx.Request] = []
    search = web_search([WikipediaBackend("en"), OpenAlexBackend()], seen, openalex_status=503)
    result = await search.search_text("t", phrases=[PHRASE])
    assert not result.complete and result.matches
    assert result.limitations[0].startswith("1 of 2 queries failed")
    assert "openalex: HTTP 503" in result.limitations[0]

    cache = InMemoryProviderCache(ttl=timedelta(hours=1))
    cached = CachedTextSourceSearch(search, cache)
    await cached.search_text("t", phrases=[PHRASE])
    await cached.search_text("t", phrases=[PHRASE])
    assert len([r for r in seen if r.url.host == "en.wikipedia.org"]) == 3  # 1 + 2, never cached


async def test_complete_results_are_cached_per_backend_set() -> None:
    seen: list[httpx.Request] = []
    cache = InMemoryProviderCache(ttl=timedelta(hours=1))
    wiki_only = CachedTextSourceSearch(web_search([WikipediaBackend("en")], seen), cache)
    both = CachedTextSourceSearch(
        web_search([WikipediaBackend("en"), OpenAlexBackend()], seen), cache
    )
    await wiki_only.search_text("t", phrases=[PHRASE])
    again = await wiki_only.search_text("t", phrases=[PHRASE])
    assert again.cached and len(seen) == 1
    other = await both.search_text("t", phrases=[PHRASE])
    assert not other.cached  # a different backend set is a different search


async def test_every_query_failing_raises_instead_of_reporting_no_matches() -> None:
    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    search = WebTextSourceSearch(
        [WikipediaBackend("en"), OpenAlexBackend()],
        results_per_phrase=3,
        timeout_seconds=1,
        transport=httpx.MockTransport(broken),
    )
    with pytest.raises(SourceSearchError, match="every search query failed"):
        await search.search_text("t", phrases=[PHRASE, "another phrase here"])


def test_a_web_search_without_backends_is_refused() -> None:
    with pytest.raises(SourceSearchError):
        WebTextSourceSearch([], results_per_phrase=3, timeout_seconds=1)


# -- Google Vision ----------------------------------------------------------------------------


def vision_search(handler: Any, **kwargs: Any) -> GoogleVisionImageSearch:
    return GoogleVisionImageSearch(
        api_key=kwargs.pop("api_key", "test-key-123"),
        max_results=10,
        timeout_seconds=5,
        transport=httpx.MockTransport(handler),
    )


async def test_google_vision_maps_bands_and_keeps_the_key_in_a_header() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "responses": [
                    {
                        "webDetection": {
                            "pagesWithMatchingImages": [
                                {
                                    "url": "https://news.example/story",
                                    "pageTitle": "Story",
                                    "fullMatchingImages": [{"url": "https://cdn.example/a.jpg"}],
                                },
                                {"url": "https://blog.example/post", "partialMatchingImages": [{}]},
                            ],
                            "fullMatchingImages": [{"url": "https://cdn.example/a.jpg"}],
                            "partialMatchingImages": [{"url": "https://cdn.example/b.jpg"}],
                            "visuallySimilarImages": [{"url": "https://cdn.example/c.jpg"}],
                        }
                    }
                ]
            },
        )

    result = await vision_search(handler).search_image(b"\xff\xd8image", metadata={})
    request = seen[0]
    assert request.url.host == "vision.googleapis.com" and not request.url.query
    assert request.headers["x-goog-api-key"] == "test-key-123"
    assert "test-key-123" not in str(request.url)
    body = json.loads(request.content)["requests"][0]
    assert base64.b64decode(body["image"]["content"]) == b"\xff\xd8image"
    assert body["features"] == [{"type": "WEB_DETECTION", "maxResults": 10}]

    by_url = {m.url: m for m in result.matches}
    assert by_url["https://news.example/story"].similarity == 1.0
    assert by_url["https://news.example/story"].source_kind == "web_page"
    assert by_url["https://blog.example/post"].similarity == 0.7
    assert by_url["https://cdn.example/a.jpg"].similarity == 1.0  # one entry, no duplicate
    assert by_url["https://cdn.example/b.jpg"].similarity == 0.7
    assert by_url["https://cdn.example/c.jpg"].similarity == 0.4
    assert len(result.matches) == 5 and all(m.published_at is None for m in result.matches)
    assert result.provider == "google_vision" and result.estimated_cost == 0.0035
    assert any("sent to Google Cloud Vision" in x for x in result.limitations)


async def test_google_vision_errors_are_clear_and_never_echo_the_key() -> None:
    def bad_key(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": {"message": "key test-key-123 rejected"}})

    with pytest.raises(SourceSearchError) as http_err:
        await vision_search(bad_key).search_image(b"img", metadata={})
    assert "403" in str(http_err.value) and "test-key-123" not in str(http_err.value)

    def inline_error(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"responses": [{"error": {"code": 3, "message": "bad"}}]})

    with pytest.raises(SourceSearchError, match="error 3"):
        await vision_search(inline_error).search_image(b"img", metadata={})

    def garbage(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>")

    with pytest.raises(SourceSearchError, match="unexpected payload"):
        await vision_search(garbage).search_image(b"img", metadata={})


async def test_google_vision_refuses_oversized_images_and_blank_keys() -> None:
    def never(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not call out")

    with pytest.raises(SourceSearchError, match="larger than"):
        await vision_search(never).search_image(b"x" * 7_000_001, metadata={})
    with pytest.raises(SourceSearchError, match="not set"):
        vision_search(never, api_key="  ")


async def test_google_vision_empty_result_is_an_empty_list() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"responses": [{}]})

    result = await vision_search(handler).search_image(b"img", metadata={})
    assert result.matches == []


# -- settings and builders --------------------------------------------------------------------

ALLOWED = ["api.openai.com", "en.wikipedia.org", "api.openalex.org", "vision.googleapis.com"]


def web_settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {"source_search_provider": "web", "outbound_allowed_hosts": ALLOWED}
    return Settings(_env_file=None, **{**base, **overrides})


def test_web_search_needs_its_hosts_on_the_allowlist() -> None:
    with pytest.raises(ValidationError, match=r"add 'en\.wikipedia\.org'"):
        Settings(_env_file=None, source_search_provider="web")
    with pytest.raises(ValidationError, match=r"add 'vision\.googleapis\.com'"):
        Settings(
            _env_file=None,
            source_search_provider="web",
            source_search_text_backends=[],
            source_search_image_backend="google_vision",
            google_vision_api_key="k",
        )
    assert web_settings().web_search_endpoints().keys() == {"wikipedia", "openalex"}


def test_unused_backends_do_not_need_hosts_and_mock_never_does() -> None:
    Settings(_env_file=None, source_search_provider="mock")
    s = web_settings(
        source_search_text_backends=["wikipedia"], outbound_allowed_hosts=["en.wikipedia.org"]
    )
    assert s.web_search_endpoints().keys() == {"wikipedia"}


def test_searxng_and_vision_need_their_settings() -> None:
    with pytest.raises(ValidationError, match="VERIXA_SEARXNG_BASE_URL"):
        web_settings(source_search_text_backends=["searxng"])
    with pytest.raises(ValidationError, match="VERIXA_GOOGLE_VISION_API_KEY"):
        web_settings(source_search_image_backend="google_vision")
    with pytest.raises(ValidationError, match="VERIXA_GOOGLE_VISION_API_KEY"):
        web_settings(source_search_image_backend="google_vision", google_vision_api_key="  ")


def test_searxng_local_http_is_allowed_in_development_but_not_production() -> None:
    dev = web_settings(
        source_search_text_backends=["searxng"], searxng_base_url="http://localhost:8888"
    )
    assert dev.web_search_endpoints() == {"searxng": "http://localhost:8888"}
    with pytest.raises(ValidationError, match="must use https"):
        web_settings(
            environment="production",
            secret_key="x" * 40,
            source_search_text_backends=["searxng"],
            searxng_base_url="http://localhost:8888",
        )
    with pytest.raises(ValidationError, match="not on VERIXA_OUTBOUND_ALLOWED_HOSTS"):
        web_settings(
            source_search_text_backends=["searxng"], searxng_base_url="https://search.example.org"
        )


def test_builders_follow_the_chosen_backends() -> None:
    s = web_settings()
    text = build_text_source_search(s)
    assert text is not None and text.name == "web"
    assert build_image_source_search(s) is None  # no image backend chosen: step is skipped

    s = web_settings(
        source_search_image_backend="google_vision", google_vision_api_key="gv-secret-xyz"
    )
    image = build_image_source_search(s)
    assert image is not None and image.name == "google_vision"
    assert "gv-secret-xyz" not in repr(s)  # the key is a SecretStr


async def test_pipeline_uses_the_web_search_providers(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[httpx.Request] = []

    def fake_text(settings: Settings, *, cache: Any = None) -> Any:
        return web_search([WikipediaBackend("en")], seen)

    monkeypatch.setattr("app.workers.dispatcher.build_text_source_search", fake_text)
    headers = await auth_headers(client)
    r = await client.post("/analysis/text", headers=headers, json={"text": ENGLISH * 3})
    aid = r.json()["id"]
    detail = (await client.get(f"/analysis/{aid}", headers=headers)).json()
    step = next(s for s in detail["steps"] if s["name"] == "search")
    assert step["status"] == "completed" and step["details"]["provider"] == "web"
    body = (await client.get(f"/analysis/{aid}/matches", headers=headers)).json()
    assert body["provider"] == "web" and body["matches"]
    assert all(m["url"].startswith("https://en.wikipedia.org/wiki/") for m in body["matches"])
    assert {r.url.host for r in seen} == {"en.wikipedia.org"}
