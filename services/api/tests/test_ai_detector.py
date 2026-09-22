import uuid
from typing import Any

import pytest
from httpx import AsyncClient

from app.config import Settings
from app.providers.ai import (
    AIDetectorError,
    CachedAIDetector,
    InMemoryDetectionCache,
    MockAIDetector,
    build_ai_detector,
    detection_cache_key,
    label_for_score,
)
from app.providers.ai.base import DetectionResult
from tests.test_image_upload import auth_headers, make_image
from tests.test_text import ENGLISH

# -- interface + mock ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("score", "label"),
    [
        (None, "unavailable"),
        (0.95, "likely_ai"),
        (0.85, "likely_ai"),
        (0.7, "uncertain"),
        (0.1, "likely_human"),
    ],
)
def test_label_thresholds(score: float | None, label: str) -> None:
    assert label_for_score(score, high=0.85, medium=0.6) == label


async def test_mock_is_deterministic_and_self_describing() -> None:
    det = MockAIDetector(high=0.85, medium=0.6)
    a = await det.detect(b"same bytes", modality="image", metadata={})
    b = await det.detect(b"same bytes", modality="image", metadata={})
    c = await det.detect(b"other bytes", modality="image", metadata={})
    assert a == b and a.score != c.score
    assert a.provider == "mock" and a.model == "mock-detector" and not a.calibrated
    assert a.score is not None and 0 <= a.score <= 1
    assert any("MOCK" in x for x in a.limitations)
    assert a.raw["mock"] is True


async def test_mock_fixed_score() -> None:
    det = MockAIDetector(high=0.85, medium=0.6, fixed_score=0.9)
    r = await det.detect("text", modality="text", metadata={})
    assert r.score == 0.9 and r.label == "likely_ai"


# -- cache ----------------------------------------------------------------------------


class CountingDetector:
    name = "counting"
    modalities = frozenset({"text"})

    def __init__(self, fail: bool = False) -> None:
        self.calls = 0
        self.fail = fail

    async def detect(
        self, content: bytes | str, *, modality: Any, metadata: Any
    ) -> DetectionResult:
        self.calls += 1
        if self.fail:
            raise AIDetectorError("upstream 503")
        return DetectionResult(
            provider="counting",
            model="m",
            model_version="1",
            modality=modality,
            score=0.5,
            label="uncertain",
            calibrated=False,
            latency_ms=42,
        )


async def test_cached_detector_serves_repeats_without_calling_provider() -> None:
    inner = CountingDetector()
    det = CachedAIDetector(inner, InMemoryDetectionCache(), model_hint="m")
    first = await det.detect("hello", modality="text", metadata={})
    second = await det.detect("hello", modality="text", metadata={})
    other = await det.detect("world", modality="text", metadata={})
    assert inner.calls == 2
    assert not first.cached and second.cached and not other.cached
    assert second.latency_ms == 0 and second.score == first.score


async def test_cache_key_includes_identity_and_content() -> None:
    k1 = detection_cache_key("x", provider="p", model="m", model_version="1", modality="text")
    k2 = detection_cache_key("x", provider="p", model="m", model_version="2", modality="text")
    k3 = detection_cache_key("y", provider="p", model="m", model_version="1", modality="text")
    assert len({k1, k2, k3}) == 3


async def test_cache_is_bounded() -> None:
    cache = InMemoryDetectionCache(max_entries=2)
    r = DetectionResult("p", "m", "1", "text", 0.1, "likely_human", False)
    for k in ("a", "b", "c"):
        await cache.set(k, r)
    assert await cache.get("a") is None and await cache.get("c") is not None


def test_build_detector_respects_setting(migrated_settings: Settings) -> None:
    migrated_settings.ai_detector_provider = "none"
    assert build_ai_detector(migrated_settings) is None
    migrated_settings.ai_detector_provider = "mock"
    det = build_ai_detector(migrated_settings)
    assert det is not None and det.name == "mock"


# -- step + API -----------------------------------------------------------------------


async def test_no_provider_means_skipped_step_and_no_ai_result(client: AsyncClient) -> None:
    headers = await auth_headers(client)
    r = await client.post(
        "/analysis/image",
        headers=headers,
        files={"file": ("a.png", make_image("PNG"), "image/png")},
    )
    aid = r.json()["id"]
    detail = (await client.get(f"/analysis/{aid}", headers=headers)).json()
    step = next(s for s in detail["steps"] if s["name"] == "ai")
    assert step["status"] == "skipped" and "no AI detector" in step["details"]["reason"]
    assert detail["status"] == "completed"
    assert (await client.get(f"/analysis/{aid}/ai", headers=headers)).status_code == 404


@pytest.fixture
def mock_ai(migrated_settings: Settings) -> Settings:
    migrated_settings.ai_detector_provider = "mock"
    return migrated_settings


async def test_mock_provider_persists_signal_for_image_and_text(
    client: AsyncClient, mock_ai: Settings
) -> None:
    headers = await auth_headers(client)
    img = await client.post(
        "/analysis/image",
        headers=headers,
        files={"file": ("a.png", make_image("PNG"), "image/png")},
    )
    txt = await client.post("/analysis/text", headers=headers, json={"text": ENGLISH})

    for created, modality in ((img, "image"), (txt, "text")):
        aid = created.json()["id"]
        detail = (await client.get(f"/analysis/{aid}", headers=headers)).json()
        step = next(s for s in detail["steps"] if s["name"] == "ai")
        assert step["status"] == "completed" and step["details"]["provider"] == "mock"

        r = await client.get(f"/analysis/{aid}/ai", headers=headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["modality"] == modality and body["provider"] == "mock"
        assert body["model"] == "mock-detector" and body["calibrated"] is False
        assert body["label"] in ("likely_ai", "uncertain", "likely_human")
        assert body["evidence_level"] in ("PROBABLE", "POSSIBLE", "UNKNOWN")
        assert body["thresholds"] == {"high": 0.85, "medium": 0.6}
        assert any("MOCK" in x for x in body["limitations"])
        assert any("not evidence of who" in x for x in body["limitations"])


async def test_repeat_content_is_served_from_cache(client: AsyncClient, mock_ai: Settings) -> None:
    headers = await auth_headers(client)
    data = make_image("JPEG", (33, 21))
    first = await client.post(
        "/analysis/image", headers=headers, files={"file": ("a.jpg", data, "image/jpeg")}
    )
    second = await client.post(
        "/analysis/image", headers=headers, files={"file": ("b.jpg", data, "image/jpeg")}
    )
    b1 = (await client.get(f"/analysis/{first.json()['id']}/ai", headers=headers)).json()
    b2 = (await client.get(f"/analysis/{second.json()['id']}/ai", headers=headers)).json()
    assert b1["score"] == b2["score"]
    assert b2["cached"] is True


async def test_ai_endpoint_enforces_ownership(client: AsyncClient, mock_ai: Settings) -> None:
    owner = await auth_headers(client, "o@example.com")
    r = await client.post("/analysis/text", headers=owner, json={"text": ENGLISH})
    aid = r.json()["id"]
    intruder = await auth_headers(client, "i@example.com")
    assert (await client.get(f"/analysis/{aid}/ai", headers=intruder)).status_code == 404
    assert (await client.get(f"/analysis/{uuid.uuid4()}/ai", headers=owner)).status_code == 404
    assert (await client.get(f"/analysis/{aid}/ai")).status_code == 401
