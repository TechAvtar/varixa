"""Application configuration loaded from environment variables.

Secrets are typed as ``SecretStr`` so they are never printed by accident.
Only non-sensitive settings should be surfaced in diagnostics endpoints.

Local development defaults to a file-based SQLite database and a local
filesystem storage directory so no external services are required. Production
uses PostgreSQL and private S3-compatible object storage via the same settings.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

StorageBackend = Literal["local", "s3"]
_DEV_SECRET = "dev-only-insecure-secret-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VERIXA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Verixa API"
    app_version: str = "0.1.0"
    environment: Literal["development", "test", "production"] = "development"
    debug: bool = False

    # Comma-separated list of allowed browser origins.
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    # Signs access tokens. Must be a long random value outside development.
    secret_key: SecretStr = SecretStr(_DEV_SECRET)
    access_token_ttl_minutes: int = Field(default=30, ge=1, le=24 * 60)
    refresh_token_ttl_days: int = Field(default=14, ge=1, le=365)

    # Root directory for all local, non-versioned runtime data (DB file, uploads).
    data_dir: Path = Path("./data")

    # SQLAlchemy URL. Defaults to SQLite under ``data_dir``; set to a
    # ``postgresql+asyncpg://`` URL for PostgreSQL.
    database_url: str = ""

    # Object storage. ``local`` writes under ``storage_local_path``;
    # ``s3`` talks to any S3-compatible bucket (never exposed publicly).
    storage_backend: StorageBackend = "local"
    storage_local_path: Path | None = None
    s3_endpoint_url: str | None = None
    s3_region: str = "auto"
    s3_bucket: str | None = None
    s3_access_key_id: SecretStr | None = None
    s3_secret_access_key: SecretStr | None = None

    @model_validator(mode="after")
    def _apply_local_defaults(self) -> "Settings":
        if not self.database_url:
            db_path = (self.data_dir / "verixa.db").as_posix()
            self.database_url = f"sqlite+aiosqlite:///{db_path}"
        if self.storage_local_path is None:
            self.storage_local_path = self.data_dir / "storage"
        return self

    @model_validator(mode="after")
    def _require_real_secret_outside_dev(self) -> "Settings":
        secret = self.secret_key.get_secret_value()
        if self.environment == "production" and (secret == _DEV_SECRET or len(secret) < 32):
            raise ValueError(
                "VERIXA_SECRET_KEY must be a random value of at least 32 characters in production"
            )
        return self

    @model_validator(mode="after")
    def _require_s3_settings(self) -> "Settings":
        if self.storage_backend == "s3":
            missing = [
                name
                for name in ("s3_bucket", "s3_access_key_id", "s3_secret_access_key")
                if getattr(self, name) is None
            ]
            if missing:
                raise ValueError(
                    "storage_backend='s3' requires: "
                    + ", ".join(f"VERIXA_{m.upper()}" for m in missing)
                )
        return self

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    def ensure_local_dirs(self) -> None:
        """Create local data directories. Safe to call repeatedly."""
        if self.is_sqlite:
            self.data_dir.mkdir(parents=True, exist_ok=True)
        if self.storage_backend == "local" and self.storage_local_path is not None:
            self.storage_local_path.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
