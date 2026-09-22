"""Retention sweeper: periodic in-process task, or a one-shot command.

python -m app.workers.retention          # one sweep, prints the JSON report
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings, get_settings
from app.database import create_engine, create_session_factory
from app.providers.storage import build_storage
from app.providers.storage.base import ObjectStorage
from app.services.retention import RetentionReport, RetentionService

log = logging.getLogger("verixa.retention")


async def sweep_once(
    session_factory: async_sessionmaker[AsyncSession], storage: ObjectStorage, settings: Settings
) -> RetentionReport:
    async with session_factory() as session:
        return await RetentionService(session, storage, settings).run_once()


async def run_periodically(
    session_factory: async_sessionmaker[AsyncSession],
    storage: ObjectStorage,
    settings: Settings,
    *,
    sleep: Callable[[float], asyncio.Future[None]] | None = None,
) -> None:
    """Loop forever; one failed sweep is logged and the loop continues."""
    interval = settings.retention_sweep_interval_minutes * 60
    while True:
        try:
            await sweep_once(session_factory, storage, settings)
        except Exception:
            log.exception("retention sweep failed")
        await asyncio.sleep(interval)


async def _main() -> int:
    settings = get_settings()
    settings.ensure_local_dirs()
    engine = create_engine(settings)
    try:
        report = await sweep_once(create_session_factory(engine), build_storage(settings), settings)
    finally:
        await engine.dispose()
    print(json.dumps(report.to_json(), indent=2))
    return 1 if report.errors else 0


if __name__ == "__main__":  # pragma: no cover - manual entry point
    logging.basicConfig(level=logging.INFO)
    sys.exit(asyncio.run(_main()))
