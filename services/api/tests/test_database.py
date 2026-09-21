"""Migration and model round-trip tests against SQLite (the local/test engine)."""

import uuid

import pytest
from alembic import command
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.database import create_engine
from app.models import Analysis, AnalysisFile, Evidence, ProviderCall, User
from app.models.enums import (
    AnalysisStatus,
    AnalysisType,
    EvidenceLevel,
    ProviderCallStatus,
    UserRole,
)
from tests.conftest import alembic_config

EXPECTED_TABLES = {"users", "analyses", "analysis_files", "evidence", "provider_calls"}


async def test_migrations_upgrade_and_downgrade(migrated_settings: Settings) -> None:
    engine = create_engine(migrated_settings)
    try:
        async with engine.connect() as conn:
            tables = set(await conn.run_sync(lambda c: inspect(c).get_table_names()))
        assert tables >= EXPECTED_TABLES

        command.downgrade(alembic_config(migrated_settings.database_url), "base")
        async with engine.connect() as conn:
            tables = set(await conn.run_sync(lambda c: inspect(c).get_table_names()))
        assert not (EXPECTED_TABLES & tables)
    finally:
        await engine.dispose()


async def test_models_round_trip(session: AsyncSession) -> None:
    user = User(email="analyst@example.com", name="Analyst")
    analysis = Analysis(user=user, type=AnalysisType.IMAGE, title="Sample")
    analysis.files.append(
        AnalysisFile(object_key="private/key", sha256="a" * 64, size_bytes=1234, width=10)
    )
    analysis.evidence.append(
        Evidence(
            category="provenance",
            level=EvidenceLevel.UNKNOWN,
            claim="No content credentials were found.",
            source="c2pa",
            details={"has_c2pa": False},
        )
    )
    analysis.provider_calls.append(
        ProviderCall(
            provider="mock",
            operation="detect",
            model_version="mock-1",
            status=ProviderCallStatus.SUCCESS,
            latency_ms=12,
            response_json={"score": 0.5},
        )
    )
    session.add(user)
    await session.commit()

    loaded = (await session.execute(select(Analysis))).scalar_one()
    assert isinstance(loaded.id, uuid.UUID)
    assert loaded.status == AnalysisStatus.QUEUED
    assert loaded.created_at is not None

    await session.refresh(loaded, ["user", "files", "evidence", "provider_calls"])
    assert loaded.user.role == UserRole.USER
    assert loaded.files[0].sha256 == "a" * 64
    assert loaded.evidence[0].details == {"has_c2pa": False}
    assert loaded.provider_calls[0].response_json == {"score": 0.5}


async def test_user_email_is_unique(session: AsyncSession) -> None:
    session.add_all([User(email="dup@example.com"), User(email="dup@example.com")])
    with pytest.raises(IntegrityError):
        await session.commit()
