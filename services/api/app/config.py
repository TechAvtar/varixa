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

    # Observability. Logs are structured (text for terminals, json for shippers); metrics are
    # aggregates only and need a bearer token when one is set (always, in production).
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["text", "json"] = "text"
    metrics_enabled: bool = True
    metrics_token: SecretStr | None = None

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

    # Abuse controls (docs/09). Attempts are counted per process; 0 disables a limit.
    # Login: failed attempts per email and per client address inside the window.
    login_max_attempts: int = Field(default=10, ge=0, le=10_000)
    login_max_attempts_per_ip: int = Field(default=50, ge=0, le=100_000)
    login_window_minutes: int = Field(default=15, ge=1, le=24 * 60)
    # Registration attempts per client address per hour.
    register_max_per_hour: int = Field(default=20, ge=0, le=100_000)
    # Only enable behind a reverse proxy that overwrites X-Forwarded-For.
    trust_proxy_headers: bool = False

    # SSRF guard: hosts (and their subdomains) that provider adapters may call over https.
    # Plain-http localhost endpoints are additionally allowed outside production for stubs.
    outbound_allowed_hosts: list[str] = Field(default_factory=lambda: ["api.openai.com"])

    # Metadata extraction engine: "auto" prefers ExifTool when installed, else Pillow.
    metadata_engine: Literal["auto", "exiftool", "pillow"] = "auto"
    exiftool_path: str | None = None
    exiftool_timeout_seconds: float = Field(default=30.0, ge=1, le=300)

    # C2PA / Content Credentials engine: "auto" uses c2patool when installed, else none.
    provenance_engine: Literal["auto", "c2patool", "none"] = "auto"
    c2patool_path: str | None = None
    c2patool_timeout_seconds: float = Field(default=30.0, ge=1, le=300)
    # Let c2patool fetch manifests referenced by URL inside the asset. Off: a subprocess must
    # never reach the network on the asset's say-so; the reference is reported instead.
    # Refused in production (preflight). Engines older than 0.28 cannot switch it off.
    c2pa_remote_manifest_fetch: bool = False
    # Trust evaluation of the signing certificate: "bundled" uses the official C2PA trust list
    # shipped with the code (scripts/refresh_trust_list.py refreshes it), "custom" uses your own
    # local PEM files, "off" skips the trust run (reports say so). Local files only; never URLs.
    c2pa_trust_mode: Literal["bundled", "custom", "off"] = "bundled"
    c2pa_trust_anchors_path: Path | None = None
    c2pa_allowed_list_path: Path | None = None
    c2pa_trust_config_path: Path | None = None

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

    # Forensics: embedded-thumbnail comparison (correlation below which the thumbnail shows
    # different content, outlier threshold and band for a localised difference, aspect tolerance).
    thumbnail_min_correlation: float = Field(default=0.9, ge=0.0, le=1.0)
    thumbnail_outlier_sigma: float = Field(default=2.5, ge=0.5, le=10.0)
    thumbnail_anomaly_min_fraction: float = Field(default=0.01, ge=0.0, le=1.0)
    thumbnail_anomaly_max_fraction: float = Field(default=0.3, ge=0.0, le=1.0)
    thumbnail_aspect_tolerance: float = Field(default=0.05, ge=0.0, le=1.0)

    # Forensics: JPEG ghosts (pixel cap before centre-cropping, dip depth that counts as a
    # ghost, block-fraction band for a localised ghost, DC-histogram periodicity threshold).
    double_compression_max_pixels: int = Field(default=2_500_000, ge=65_536)
    double_compression_min_depth: float = Field(default=0.12, ge=0.01, le=1.0)
    double_compression_anomaly_min_fraction: float = Field(default=0.01, ge=0.0, le=1.0)
    double_compression_anomaly_max_fraction: float = Field(default=0.6, ge=0.0, le=1.0)
    double_compression_periodicity_min: float = Field(default=5.0, ge=1.0, le=1000.0)

    # Evidence engine (docs/07). Rule thresholds live here, never in the rules themselves.
    language_probable_confidence: float = Field(default=0.9, ge=0.0, le=1.0)
    forensic_families_for_strong: int = Field(default=2, ge=1, le=3)
    # Confidence attached to a record when the rule has no better number of its own.
    evidence_confidence_verified: float = Field(default=1.0, ge=0.0, le=1.0)
    evidence_confidence_strong: float = Field(default=0.8, ge=0.0, le=1.0)
    evidence_confidence_probable: float = Field(default=0.65, ge=0.0, le=1.0)
    evidence_confidence_possible: float = Field(default=0.4, ge=0.0, le=1.0)
    # Per-rule level overrides, e.g. {"forensics.ela.anomaly": "UNKNOWN"}. A rule can be made
    # more conservative than docs/07 but never stronger than its ceiling (enforced by the engine).
    evidence_level_overrides: dict[str, str] = Field(default_factory=dict)
    # How much each conflict record lowers the synthesis confidence.
    evidence_conflict_penalty: float = Field(default=0.25, ge=0.0, le=1.0)

    # LLM synthesis (explanation layer only). "none" skips the step; "mock" is deterministic;
    # "openai" needs VERIXA_OPENAI_API_KEY. Only structured evidence is ever sent.
    llm_provider: Literal["none", "mock", "openai"] = "none"
    llm_timeout_seconds: float = Field(default=60.0, ge=1, le=300)
    llm_prompt_version: str = Field(default="v1", min_length=1, max_length=16)
    openai_api_key: SecretStr | None = None
    openai_model: str = Field(default="gpt-4o-mini", min_length=1, max_length=128)
    openai_base_url: str = "https://api.openai.com/v1"
    # USD per million tokens, for the audit trail's cost estimate (0 = unknown).
    openai_cost_per_million_input: float = Field(default=0.0, ge=0.0)
    openai_cost_per_million_output: float = Field(default=0.0, ge=0.0)

    # Retention (docs/09). Hours/days of 0 disable the corresponding pass.
    raw_content_retention_hours: int = Field(default=24, ge=0, le=24 * 3650)
    provider_response_retention_days: int = Field(default=30, ge=0, le=3650)
    deleted_record_grace_days: int = Field(default=7, ge=0, le=3650)
    analysis_retention_days: int = Field(default=0, ge=0, le=36500)
    retention_sweep_interval_minutes: int = Field(default=60, ge=0, le=24 * 60)

    # Usage limits per user (0 = unlimited): analyses per calendar month, bytes currently held,
    # and provider cost (USD) per calendar month after which paid steps are skipped.
    usage_monthly_analysis_limit: int = Field(default=0, ge=0)
    usage_storage_limit_bytes: int = Field(default=0, ge=0)
    usage_monthly_provider_cost_limit: float = Field(default=0.0, ge=0.0)

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
        secret = self.secret_key.get_secret_value().strip()
        if not secret and self.environment != "production":
            # A blank VERIXA_SECRET_KEY= (as in .env.example) must not break local sign-in:
            # an empty HMAC key makes every token operation fail.
            self.secret_key = SecretStr(_DEV_SECRET)
            secret = _DEV_SECRET
        if self.environment == "production" and (secret == _DEV_SECRET or len(secret) < 32):
            raise ValueError(
                "VERIXA_SECRET_KEY must be a random value of at least 32 characters in production"
            )
        return self

    @model_validator(mode="after")
    def _evidence_settings_consistent(self) -> "Settings":
        order = (
            self.evidence_confidence_possible,
            self.evidence_confidence_probable,
            self.evidence_confidence_strong,
            self.evidence_confidence_verified,
        )
        if list(order) != sorted(order):
            raise ValueError(
                "VERIXA_EVIDENCE_CONFIDENCE_* must be ordered possible <= probable <= strong "
                "<= verified"
            )
        allowed = {"VERIFIED", "STRONG", "PROBABLE", "POSSIBLE", "UNKNOWN"}
        bad = {k: v for k, v in self.evidence_level_overrides.items() if v not in allowed}
        if bad:
            raise ValueError(f"VERIXA_EVIDENCE_LEVEL_OVERRIDES has invalid levels: {bad}")
        return self

    @model_validator(mode="after")
    def _ai_thresholds_ordered(self) -> "Settings":
        if self.ai_score_medium > self.ai_score_high:
            raise ValueError("VERIXA_AI_SCORE_MEDIUM must not exceed VERIXA_AI_SCORE_HIGH")
        return self

    @model_validator(mode="after")
    def _trust_files_are_local(self) -> "Settings":
        paths = {
            "VERIXA_C2PA_TRUST_ANCHORS_PATH": self.c2pa_trust_anchors_path,
            "VERIXA_C2PA_ALLOWED_LIST_PATH": self.c2pa_allowed_list_path,
            "VERIXA_C2PA_TRUST_CONFIG_PATH": self.c2pa_trust_config_path,
        }
        for name, path in paths.items():
            if path is None:
                continue
            # Path() collapses "https://h" to "https:/h", so match the scheme, not "://".
            text = str(path).strip().lower().replace("\\", "/")
            if text.startswith(("http:", "https:", "ftp:", "file:")):
                raise ValueError(f"{name} must be a local file, not a URL")
            if not path.is_file():
                raise ValueError(f"{name} does not exist or is not a file")
        if self.c2pa_trust_mode == "custom" and not (
            self.c2pa_trust_anchors_path or self.c2pa_allowed_list_path
        ):
            raise ValueError(
                "VERIXA_C2PA_TRUST_MODE=custom needs VERIXA_C2PA_TRUST_ANCHORS_PATH or "
                "VERIXA_C2PA_ALLOWED_LIST_PATH"
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

    def production_problems(self) -> list[str]:
        """Configuration that must not reach production (docs/09, infra/README.md).

        Checked by ``python -m app.preflight`` before migrations run in a deployment; kept
        out of the validators so tests and local tooling can still build production-mode
        settings against SQLite.
        """
        if self.environment != "production":
            return []
        problems: list[str] = []
        if self.debug:
            problems.append("VERIXA_DEBUG must be false")
        if self.is_sqlite:
            problems.append("VERIXA_DATABASE_URL must point at PostgreSQL, not SQLite")
        if self.storage_backend != "s3":
            problems.append("VERIXA_STORAGE_BACKEND must be s3 (private bucket)")
        if not self.api_public_url.startswith("https://"):
            problems.append("VERIXA_API_PUBLIC_URL must be an https origin")
        insecure = [o for o in self.cors_origins if not o.startswith("https://")]
        if insecure:
            problems.append(f"VERIXA_CORS_ORIGINS must be https origins only: {insecure}")
        if self.metrics_enabled and self.metrics_token is None:
            problems.append("VERIXA_METRICS_TOKEN must be set while metrics are enabled")
        if self.c2pa_remote_manifest_fetch:
            problems.append(
                "VERIXA_C2PA_REMOTE_MANIFEST_FETCH must be false (no subprocess network access)"
            )
        return problems

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
