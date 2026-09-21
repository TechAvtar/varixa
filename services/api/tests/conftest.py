from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.database import create_engine, create_session_factory
from app.main import create_app

API_ROOT = Path(__file__).resolve().parents[1]


def alembic_config(database_url: str) -> Config:
    cfg = Config(str(API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_ROOT / "alembic"))
    # Equivalent to `alembic -x url=<database_url>`; env.py reads it.
    cfg.cmd_opts = type("Opts", (), {"x": [f"url={database_url}"]})()
    return cfg


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        cors_origins=["http://testserver"],
        data_dir=tmp_path / "data",
    )


@pytest.fixture
def migrated_settings(settings: Settings) -> Settings:
    """Settings whose SQLite database has every migration applied."""
    settings.ensure_local_dirs()
    command.upgrade(alembic_config(settings.database_url), "head")
    return settings


@pytest.fixture
async def session(migrated_settings: Settings) -> AsyncIterator[AsyncSession]:
    engine = create_engine(migrated_settings)
    factory = create_session_factory(engine)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest.fixture
async def client(migrated_settings: Settings) -> AsyncIterator[AsyncClient]:
    app = create_app(migrated_settings)
    # ASGITransport does not run lifespan events; enter it explicitly so the
    # engine/session factory exist exactly as they would under uvicorn.
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as c:
            yield c
