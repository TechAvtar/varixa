from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.config import Settings


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
