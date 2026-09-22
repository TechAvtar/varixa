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

    # Public origin of this API, used to build signed download URLs for local storage.
    api_public_url: str = "http://localhost:8000"
    # Lifetime of signed download URLs.
    signed_url_ttl_seconds: int = Field(default=300, ge=10, le=3600)

    # Metadata extraction engine: "auto" prefers ExifTool when installed, else Pillow.
    metadata_engine: Literal["auto", "exiftool", "pillow"] = "auto"
    exiftool_path: str | None = None
    exiftool_timeout_seconds: float = Field(default=30.0, ge=1, le=300)

    # C2PA / Content Credentials engine: "auto" uses c2patool when installed, else none.
    provenance_engine: Literal["auto", "c2patool", "none"] = "auto"
    c2patool_path: str | None = None
    c2patool_timeout_seconds: float = Field(default=30.0, ge=1, le=300)

    # Near-duplicate threshold: max Hamming distance (bits) on pHash or dHash.
    fingerprint_near_threshold: int = Field(default=10, ge=0, le=64)

    # AI-generation detector. "none" disables the step (report says UNKNOWN); "mock" is a
    # deterministic stand-in for development. Real adapters register by name in providers/ai.
    ai_detector_provider: Literal["none", "mock"] = "none"
    ai_detector_timeout_seconds: float = Field(default=30.0, ge=1, le=300)
    # Score thresholds -> evidence levels (docs/07): >= high PROBABLE, >= medium POSSIBLE.
    ai_score_high: float = Field(default=0.85, ge=0.0, le=1.0)
    ai_score_medium: float = Field(default=0.6, ge=0.0, le=1.0)

    # Forensics: Error Level Analysis (JPEG only). Thresholds live here, not in code.
    ela_quality: int = Field(default=95, ge=50, le=100)
    ela_max_side: int = Field(default=3000, ge=256, le=8000)
    ela_outlier_sigma: float = Field(default=2.5, ge=0.5, le=10.0)
    ela_anomaly_min_fraction: float = Field(default=0.005, ge=0.0, le=1.0)
    ela_anomaly_max_fraction: float = Field(default=0.2, ge=0.0, le=1.0)

    # Forensics: compression block-grid detection threshold (relative strength of an 8 px phase).
    compression_grid_min_strength: float = Field(default=0.08, ge=0.0, le=5.0)

    # Forensics: resampling spectral-peak threshold (peak magnitude / local background).
    resampling_min_peak_ratio: float = Field(default=5.0, ge=1.0, le=100.0)

    # Forensics: noise consistency (block size, outlier multiple of the IQR, anomaly band).
    noise_block_size: int = Field(default=32, ge=16, le=128)
    noise_outlier_k: float = Field(default=3.0, ge=0.5, le=20.0)
    noise_anomaly_min_fraction: float = Field(default=0.005, ge=0.0, le=1.0)
    noise_anomaly_max_fraction: float = Field(default=0.25, ge=0.0, le=1.0)

    # Forensics: copy-move block matching (working size, matching block pairs per displacement,
    # minimum displacement so overlapping neighbours never count).
    copy_move_max_side: int = Field(default=1024, ge=256, le=4096)
    copy_move_min_matches: int = Field(default=200, ge=10, le=100_000)
    copy_move_min_shift: int = Field(default=32, ge=16, le=1024)

    # Persistent provider-result cache (content hash + provider/model/version). 0 disables.
    provider_cache_ttl_hours: int = Field(default=24 * 7, ge=0, le=24 * 365)

    # Reverse-image / phrase source search. "none" skips the step; "mock" is a stand-in.
    source_search_provider: Literal["none", "mock"] = "none"
    source_search_timeout_seconds: float = Field(default=30.0, ge=1, le=300)
    text_search_max_phrases: int = Field(default=5, ge=1, le=20)

    # Text near-duplicate threshold: minimum estimated Jaccard similarity (0-1) of shingle sets.
    text_near_threshold: float = Field(default=0.5, ge=0.0, le=1.0)

    # Text input cap (characters of the original, before normalisation).
    max_text_chars: int = Field(default=200_000, ge=100)

    # Upload limits (untrusted input). Pixels are checked from the header before decoding.
    max_upload_bytes: int = Field(default=25 * 1024 * 1024, ge=1024)
    max_image_pixels: int = Field(default=40_000_000, ge=10_000)

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
    def _ai_thresholds_ordered(self) -> "Settings":
        if self.ai_score_medium > self.ai_score_high:
            raise ValueError("VERIXA_AI_SCORE_MEDIUM must not exceed VERIXA_AI_SCORE_HIGH")
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
        # Scratch space for engines that can only read files (c2patool).
        (self.data_dir / "tmp").mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
