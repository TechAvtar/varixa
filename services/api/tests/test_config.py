from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.preflight import main as preflight


def _settings(**overrides: Any) -> Settings:
    # _env_file=None isolates tests from a developer's local .env file.
    return Settings(_env_file=None, **overrides)


def test_defaults_to_sqlite_and_local_storage(tmp_path: Path) -> None:
    s = _settings(data_dir=tmp_path)
    assert s.is_sqlite
    assert s.database_url == f"sqlite+aiosqlite:///{(tmp_path / 'verixa.db').as_posix()}"
    assert s.storage_backend == "local"
    assert s.storage_local_path == tmp_path / "storage"


def test_explicit_database_url_is_kept() -> None:
    url = "postgresql+asyncpg://u:p@localhost:5432/verixa"
    s = _settings(database_url=url)
    assert s.database_url == url
    assert not s.is_sqlite


def test_ensure_local_dirs_creates_directories(tmp_path: Path) -> None:
    s = _settings(data_dir=tmp_path / "nested")
    s.ensure_local_dirs()
    assert (tmp_path / "nested").is_dir()
    assert (tmp_path / "nested" / "storage").is_dir()


def test_s3_backend_requires_credentials() -> None:
    with pytest.raises(ValidationError, match="VERIXA_S3_BUCKET"):
        _settings(storage_backend="s3")


def test_s3_secrets_are_not_exposed_in_repr() -> None:
    s = _settings(
        storage_backend="s3",
        s3_bucket="b",
        s3_access_key_id="AKIA-VISIBLE",
        s3_secret_access_key="super-secret-value",
    )
    assert "super-secret-value" not in repr(s)
    assert "super-secret-value" not in str(s.model_dump())
    assert s.s3_secret_access_key is not None
    assert s.s3_secret_access_key.get_secret_value() == "super-secret-value"


def _production(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "environment": "production",
        "secret_key": "s" * 48,
        "database_url": "postgresql+asyncpg://verixa:pw@db:5432/verixa",
        "storage_backend": "s3",
        "s3_bucket": "verixa-private",
        "s3_access_key_id": "key",
        "s3_secret_access_key": "secret",
        "api_public_url": "https://app.example.com",
        "cors_origins": ["https://app.example.com"],
        "metrics_token": "metrics-token-value",
    }
    base.update(overrides)
    return _settings(**base)


def test_production_problems_empty_for_a_deployable_configuration() -> None:
    assert _production().production_problems() == []


def test_production_problems_ignored_outside_production(tmp_path: Path) -> None:
    assert _settings(data_dir=tmp_path, debug=True).production_problems() == []


@pytest.mark.parametrize(
    ("overrides", "fragment"),
    [
        ({"debug": True}, "VERIXA_DEBUG"),
        ({"database_url": ""}, "VERIXA_DATABASE_URL"),
        ({"storage_backend": "local"}, "VERIXA_STORAGE_BACKEND"),
        ({"api_public_url": "http://app.example.com"}, "VERIXA_API_PUBLIC_URL"),
        ({"cors_origins": ["http://localhost:3000"]}, "VERIXA_CORS_ORIGINS"),
        ({"metrics_token": None}, "VERIXA_METRICS_TOKEN"),
        ({"c2pa_remote_manifest_fetch": True}, "VERIXA_C2PA_REMOTE_MANIFEST_FETCH"),
    ],
)
def test_production_problems_name_the_variable(overrides: dict[str, Any], fragment: str) -> None:
    found = _production(**overrides).production_problems()
    assert len(found) == 1 and fragment in found[0]


def test_production_metrics_token_not_needed_when_metrics_disabled() -> None:
    assert _production(metrics_token=None, metrics_enabled=False).production_problems() == []


def test_preflight_exit_codes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import app.preflight as module

    monkeypatch.setattr(module, "get_settings", lambda: _production(debug=True))
    assert preflight([]) == 1
    assert "VERIXA_DEBUG" in capsys.readouterr().err

    monkeypatch.setattr(module, "get_settings", lambda: _production())
    assert preflight([]) == 0
    assert "configuration ok (production)" in capsys.readouterr().out


def test_preflight_reports_invalid_settings(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import app.preflight as module

    def boom() -> Settings:
        return _settings(environment="production")  # dev secret key -> ValidationError

    monkeypatch.setattr(module, "get_settings", boom)
    assert preflight([]) == 1
    err = capsys.readouterr().err
    assert "configuration invalid" in err and "VERIXA_SECRET_KEY" in err


def test_blank_secret_key_falls_back_to_the_dev_default_outside_production(tmp_path: Path) -> None:
    s = _settings(data_dir=tmp_path, secret_key="")
    assert s.secret_key.get_secret_value() not in ("", " ")
    assert len(s.secret_key.get_secret_value()) >= 16


def test_blank_secret_key_refused_in_production() -> None:
    with pytest.raises(ValidationError, match="VERIXA_SECRET_KEY"):
        _production(secret_key="")


def test_trust_paths_must_be_local_files(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="must be a local file, not a URL"):
        _settings(c2pa_trust_anchors_path="https://example.net/anchors.pem")
    with pytest.raises(ValidationError, match="does not exist"):
        _settings(c2pa_trust_anchors_path=tmp_path / "missing.pem")
    with pytest.raises(ValidationError, match="custom needs"):
        _settings(c2pa_trust_mode="custom")
    pem = tmp_path / "anchors.pem"
    pem.write_text("-----BEGIN CERTIFICATE-----\nMA==\n-----END CERTIFICATE-----\n")
    s = _settings(c2pa_trust_mode="custom", c2pa_trust_anchors_path=pem)
    assert s.c2pa_trust_anchors_path == pem
    assert _settings().c2pa_trust_mode == "bundled"
