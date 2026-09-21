"""Domain enumerations stored as short strings (portable across DB engines)."""

from enum import StrEnum


class UserRole(StrEnum):
    USER = "user"
    ADMIN = "admin"


class AnalysisType(StrEnum):
    IMAGE = "image"
    TEXT = "text"


class AnalysisStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class EvidenceLevel(StrEnum):
    """Evidence classification: never a claim of authorship or factual truth."""

    VERIFIED = "VERIFIED"
    STRONG = "STRONG"
    PROBABLE = "PROBABLE"
    POSSIBLE = "POSSIBLE"
    UNKNOWN = "UNKNOWN"


class ProviderCallStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"
