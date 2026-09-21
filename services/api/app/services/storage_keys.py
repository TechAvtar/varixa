"""Deterministic object-key layout. Keys are internal and never exposed to clients."""

import uuid

# All keys carry the owning user id so retention/deletion can sweep by prefix.


def upload_key(user_id: uuid.UUID, analysis_id: uuid.UUID, sha256: str, extension: str) -> str:
    ext = extension.lstrip(".").lower()
    return f"uploads/{user_id}/{analysis_id}/{sha256}.{ext}"


def artifact_key(user_id: uuid.UUID, analysis_id: uuid.UUID, name: str) -> str:
    return f"artifacts/{user_id}/{analysis_id}/{name}"


def report_key(user_id: uuid.UUID, analysis_id: uuid.UUID, report_id: uuid.UUID, fmt: str) -> str:
    return f"reports/{user_id}/{analysis_id}/{report_id}.{fmt.lower()}"


def analysis_prefix(user_id: uuid.UUID, analysis_id: uuid.UUID) -> tuple[str, ...]:
    return (
        f"uploads/{user_id}/{analysis_id}/",
        f"artifacts/{user_id}/{analysis_id}/",
        f"reports/{user_id}/{analysis_id}/",
    )
