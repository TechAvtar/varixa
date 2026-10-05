"""Serverless hosting (Vercel): settings defaults, inline analysis execution, dependencies."""

import tomllib
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from pydantic import SecretStr

from app.config import Settings
from app.workers import BackgroundTaskDispatcher, InlineDispatcher
from tests.test_image_upload import auth_headers
from tests.test_text import ENGLISH


def test_vercel_environment_switches_to_serverless_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("VERCEL", raising=False)
    local = Settings(_env_file=None)
    assert local.data_dir == Path("./data")
    assert local.retention_sweep_interval_minutes == 60
    assert local.analysis_execution == "background"

    monkeypatch.setenv("VERCEL", "1")
    hosted = Settings(_env_file=None)
    assert hosted.data_dir == Path("/tmp/verixa")  # the only writable path on Vercel
    assert hosted.retention_sweep_interval_minutes == 0  # no in-process timers
    assert hosted.analysis_execution == "inline"  # no work after the response


def test_explicit_settings_beat_the_vercel_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VERCEL", "1")
    s = Settings(
        _env_file=None,
        data_dir=Path("/srv/data"),
        retention_sweep_interval_minutes=15,
        analysis_execution="background",
    )
    assert s.data_dir == Path("/srv/data")
    assert s.retention_sweep_interval_minutes == 15
    assert s.analysis_execution == "background"


def test_cron_secret_is_read_from_either_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CRON_SECRET", raising=False)
    monkeypatch.delenv("VERIXA_CRON_SECRET", raising=False)
    assert Settings(_env_file=None).cron_secret is None
    monkeypatch.setenv("CRON_SECRET", "from-vercel")
    secret = Settings(_env_file=None).cron_secret
    assert secret is not None and secret.get_secret_value() == "from-vercel"
    assert "from-vercel" not in repr(Settings(_env_file=None))


def test_production_drivers_are_core_dependencies() -> None:
    """Serverless installers read only [project].dependencies, not the extras."""
    project = tomllib.loads(
        (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]
    names = {d.split(">")[0].split("[")[0].strip().lower() for d in project["dependencies"]}
    assert {"asyncpg", "boto3"} <= names
    assert "postgres" in project["optional-dependencies"]  # existing install commands still work


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record which dispatcher the routes pick, while still running the real one."""
    calls: list[str] = []
    real_inline = InlineDispatcher.dispatch
    real_background = BackgroundTaskDispatcher.dispatch

    async def inline(self: InlineDispatcher, analysis_id: Any) -> None:
        calls.append("inline")
        await real_inline(self, analysis_id)

    async def background(self: BackgroundTaskDispatcher, analysis_id: Any) -> None:
        calls.append("background")
        await real_background(self, analysis_id)

    monkeypatch.setattr(InlineDispatcher, "dispatch", inline)
    monkeypatch.setattr(BackgroundTaskDispatcher, "dispatch", background)
    return calls


@pytest.mark.parametrize("mode", ["inline", "background"])
async def test_the_configured_execution_mode_runs_the_analysis(
    client: AsyncClient, migrated_settings: Settings, spy: list[str], mode: str
) -> None:
    migrated_settings.analysis_execution = mode  # type: ignore[assignment]
    headers = await auth_headers(client, email=f"{mode}@example.com")
    created = await client.post("/analysis/text", headers=headers, json={"text": ENGLISH * 3})
    assert created.status_code == 201
    assert spy == [mode]
    detail = (await client.get(f"/analysis/{created.json()['id']}", headers=headers)).json()
    assert detail["status"] == "completed"
    assert detail["steps"]


async def test_inline_mode_finishes_the_analysis_before_the_upload_answers(
    client: AsyncClient, migrated_settings: Settings
) -> None:
    """The point of inline mode: nothing is left to run after the response."""
    from tests.test_image_upload import make_image

    migrated_settings.analysis_execution = "inline"
    headers = await auth_headers(client, email="inline-image@example.com")
    created = await client.post(
        "/analysis/image",
        headers=headers,
        files={"file": ("a.png", make_image("PNG"), "image/png")},
    )
    assert created.status_code == 201
    detail = (await client.get(f"/analysis/{created.json()['id']}", headers=headers)).json()
    assert detail["status"] == "completed" and detail["steps"]


def test_secret_settings_are_typed() -> None:
    assert isinstance(Settings(_env_file=None, cron_secret="x").cron_secret, SecretStr)
