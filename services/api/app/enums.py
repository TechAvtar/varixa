"""Domain enumerations shared by models, schemas and services.

Stored as short strings (portable across DB engines). Lives at the app root so
every layer may import it without crossing a layering boundary.
"""

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
    CACHED = "cached"
    FAILED = "failed"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"


class StepStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
