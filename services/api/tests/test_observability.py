"""T041: structured logs with correlation ids, request/step/provider metrics, health checks."""

import json
import logging
import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from pydantic import SecretStr

from app.config import Settings
from app.enums import ProviderCallStatus
from app.services.provider_calls import ProviderCallRecorder
from app.utils import observability
from app.utils.metrics import MetricsRegistry, registry
from tests.test_image_upload import auth_headers, make_image
from tests.test_text import ENGLISH


@pytest.fixture(autouse=True)
def fresh_registry() -> None:
    registry.reset()


def _json_lines(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    formatter = observability.JsonFormatter()
    return [json.loads(formatter.format(r)) for r in caplog.records]


# -- structured logging --------------------------------------------------------------------------


def test_json_formatter_emits_one_object_with_context_and_extras() -> None:
    token = observability.request_id_var.set("req-1")
    aid = observability.analysis_id_var.set("an-1")
    try:
        record = logging.LogRecord(
            "verixa.test", logging.INFO, __file__, 1, "hello %s", ("x",), None
        )
        record.duration_ms = 12
        assert observability.ContextFilter().filter(record)
    finally:
        observability.request_id_var.reset(token)
        observability.analysis_id_var.reset(aid)
    payload = json.loads(observability.JsonFormatter().format(record))
    assert payload["msg"] == "hello x" and payload["level"] == "INFO"
    assert payload["request_id"] == "req-1" and payload["analysis_id"] == "an-1"
    assert payload["duration_ms"] == 12 and payload["ts"].endswith("+00:00")
    text = observability.KeyValueFormatter().format(record)
    assert "request_id=req-1" in text and "duration_ms=12" in text


def test_configure_logging_installs_one_handler_only() -> None:
    observability.configure_logging(level="INFO", fmt="json")
    observability.configure_logging(level="DEBUG", fmt="text")
    ours = [h for h in logging.getLogger().handlers if h.get_name() == "verixa"]
    assert len(ours) == 1 and isinstance(ours[0].formatter, observability.KeyValueFormatter)
    assert logging.getLogger("uvicorn.access").level == logging.WARNING


async def test_request_log_carries_route_status_duration_and_never_the_query(
    client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="verixa.http")
    headers = await auth_headers(client)
    r = await client.get(
        f"/analysis/{uuid.uuid4()}?secret_token=abc", headers={**headers, "X-Request-ID": "trace-7"}
    )
    assert r.status_code == 404
    line = next(x for x in _json_lines(caplog) if x["msg"] == "http request" and x["status"] == 404)
    assert line["route"] == "/api/v1/analysis/{analysis_id}" and line["method"] == "GET"
    assert line["request_id"] == "trace-7" and isinstance(line["duration_ms"], int)
    assert "secret_token" not in json.dumps(line) and "abc" not in json.dumps(line)


async def test_pipeline_logs_steps_with_analysis_id(
    client: AsyncClient, migrated_settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    headers = await auth_headers(client)
    aid = (await client.post("/analysis/text", headers=headers, json={"text": ENGLISH})).json()[
        "id"
    ]
    steps = [x for x in _json_lines(caplog) if x["msg"] == "pipeline step finished"]
    assert {s["step"] for s in steps} >= {"normalize", "language", "statistics", "evidence"}
    assert all(s["analysis_id"] == aid for s in steps)
    assert all(isinstance(s["duration_ms"], int) for s in steps)
    finished = next(x for x in _json_lines(caplog) if x["msg"] == "analysis finished")
    assert finished["analysis_id"] == aid and finished["status"] == "completed"
    assert finished["type"] == "text"
    # No content anywhere in the log.
    assert ENGLISH[:40] not in caplog.text


async def test_failed_provider_calls_are_visible_as_warnings_without_payloads(
    client: AsyncClient, migrated_settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="verixa.providers")
    app = client._transport.app  # type: ignore[attr-defined]
    async with app.state.session_factory() as db:
        await ProviderCallRecorder(db).record(
            analysis_id=None,
            provider="paid",
            operation="ai.detect",
            status=ProviderCallStatus.FAILED,
            latency_ms=250,
            error={"code": "HTTP_503", "message": "raw provider body sk-verysecretkey12345"},
        )
        await db.commit()
    warning = next(r for r in caplog.records if r.levelno == logging.WARNING)
    payload = json.loads(observability.JsonFormatter().format(warning))
    assert payload["provider"] == "paid" and payload["status"] == "failed"
    assert payload["error_code"] == "HTTP_503" and "sk-" not in json.dumps(payload)
    assert registry.provider_calls.get(provider="paid", operation="ai.detect", status="failed") == 1
    assert registry.provider_latency.get(provider="paid", operation="ai.detect").maximum == 0.25


# -- metrics ---------------------------------------------------------------------------------------


def test_registry_renders_prometheus_text() -> None:
    reg = MetricsRegistry()
    reg.record_http(method="GET", route="/api/v1/health", status=200, seconds=0.5)
    reg.record_http(method="GET", route="/api/v1/health", status=200, seconds=1.5)
    reg.record_step(step="ela", status="completed", seconds=2)
    reg.record_analysis(type="image", status="completed")
    out = reg.render()
    assert "# TYPE verixa_http_requests_total counter" in out
    assert 'verixa_http_requests_total{method="GET",route="/api/v1/health",status="200"} 2' in out
    assert 'verixa_http_request_duration_seconds_sum{method="GET",route="/api/v1/health"} 2' in out
    assert (
        'verixa_http_request_duration_seconds_max{method="GET",route="/api/v1/health"} 1.5' in out
    )
    assert 'verixa_pipeline_steps_total{status="completed",step="ela"} 1' in out
    assert 'verixa_analyses_total{status="completed",type="image"} 1' in out
    assert out.startswith("# HELP verixa_uptime_seconds") and out.endswith("\n")


async def test_metrics_endpoint_reflects_requests_and_pipelines(
    client: AsyncClient, migrated_settings: Settings
) -> None:
    headers = await auth_headers(client)
    await client.post(
        "/analysis/image",
        headers=headers,
        files={"file": ("a.jpg", make_image("JPEG", (64, 48)), "image/jpeg")},
    )
    r = await client.get("http://testserver/metrics")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    body = r.text
    assert (
        'verixa_http_requests_total{method="POST",route="/api/v1/analysis/image",status="201"} 1'
        in body
    )
    assert 'verixa_analyses_total{status="completed",type="image"} 1' in body
    assert 'verixa_pipeline_steps_total{status="completed",step="hashing"} 1' in body
    assert "verixa_pipeline_step_duration_seconds_count" in body
    # Aggregates only: no ids, emails or paths of stored objects.
    assert "@" not in body and "uploads/" not in body and headers["Authorization"][7:20] not in body


async def test_metrics_can_be_disabled_or_token_protected(
    client: AsyncClient, migrated_settings: Settings
) -> None:
    migrated_settings.metrics_token = SecretStr("scrape-me")
    assert (await client.get("http://testserver/metrics")).status_code == 401
    bad = await client.get("http://testserver/metrics", headers={"Authorization": "Bearer nope"})
    assert bad.status_code == 401 and bad.json()["error"]["code"] == "METRICS_TOKEN_REQUIRED"
    ok = await client.get(
        "http://testserver/metrics", headers={"Authorization": "Bearer scrape-me"}
    )
    assert ok.status_code == 200
    migrated_settings.metrics_enabled = False
    assert (await client.get("http://testserver/metrics")).status_code == 404


def test_metrics_refused_in_production_without_a_token(tmp_path: Any) -> None:
    from starlette.testclient import TestClient

    from app.main import create_app

    settings = Settings(
        _env_file=None,
        environment="production",
        secret_key=SecretStr("x" * 48),
        data_dir=tmp_path,
        retention_sweep_interval_minutes=0,
    )
    with TestClient(create_app(settings)) as tc:
        assert tc.get("/metrics").status_code == 404
        settings.metrics_token = SecretStr("t0ken-t0ken")
        assert (
            tc.get("/metrics", headers={"Authorization": "Bearer t0ken-t0ken"}).status_code == 200
        )


# -- health ----------------------------------------------------------------------------------------


async def test_health_reports_database_storage_providers_and_uptime(
    client: AsyncClient, migrated_settings: Settings
) -> None:
    body = (await client.get("/health")).json()
    assert body["status"] == "ok" and body["database"] == "ok" and body["storage"] == "ok"
    assert body["providers"]["storage"] == "local" and "llm" in body["providers"]
    assert body["uptime_seconds"] >= 0
    for value in body["providers"].values():
        assert "key" not in value.lower() and "://" not in value
    live = await client.get("/health/live")
    assert live.status_code == 200 and live.json() == {"status": "ok"}


async def test_health_degrades_when_storage_is_unwritable(
    client: AsyncClient, migrated_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = client._transport.app  # type: ignore[attr-defined]

    async def broken() -> bool:
        raise OSError("disk gone")

    monkeypatch.setattr(app.state.storage, "probe", broken)
    body = (await client.get("/health")).json()
    assert body["status"] == "degraded" and body["storage"] == "unavailable"
    assert "disk gone" not in json.dumps(body)
