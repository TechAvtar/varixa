"""Audit trail for provider calls (external APIs and local engines alike).

Every call records provider, operation, model/version, status, latency,
request hash, estimated cost, request id and a bounded response/error
summary. Never the request payload, never credentials, never raw content.
"""

import hashlib
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.enums import ProviderCallStatus
from app.models import Analysis, ProviderCall
from app.repositories.provider_calls import ProviderCallRepository
from app.services.usage import UsageService
from app.utils.metrics import registry

log = logging.getLogger("verixa.providers")

MAX_JSON_BYTES = 64 * 1024
MAX_ERROR_MESSAGE = 500


def request_hash(content: bytes | str) -> str:
    """SHA-256 of the request content: safe to store, never reversible to the content."""
    data = content if isinstance(content, bytes) else content.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _bounded(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if payload is None:
        return None
    encoded = json.dumps(payload, default=str)
    if len(encoded) <= MAX_JSON_BYTES:
        return payload
    return {"_truncated": True, "_bytes": len(encoded), "_preview": encoded[:2048]}


@dataclass
class CallOutcome:
    """Filled in by the caller inside ``track()`` once the provider has answered."""

    status: ProviderCallStatus = ProviderCallStatus.SUCCESS
    model_version: str | None = None
    request_id: str | None = None
    estimated_cost: float | None = None
    response: dict[str, Any] | None = None
    extra_error: dict[str, Any] = field(default_factory=dict)


class ProviderCallRecorder:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = ProviderCallRepository(session)

    async def record(
        self,
        *,
        analysis_id: uuid.UUID | None,
        provider: str,
        operation: str,
        status: ProviderCallStatus,
        latency_ms: int | None = None,
        model_version: str | None = None,
        request_id: str | None = None,
        request_hash: str | None = None,
        estimated_cost: float | None = None,
        response: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
    ) -> ProviderCall:
        row = ProviderCall(
            analysis_id=analysis_id,
            provider=provider[:64],
            operation=operation[:64],
            model_version=model_version[:128] if model_version else None,
            request_id=request_id[:128] if request_id else None,
            status=status,
            latency_ms=latency_ms,
            estimated_cost=estimated_cost,
            request_hash=request_hash,
            response_json=_bounded(response),
            error_json=_bounded(error),
        )
        await self._repo.add(row)
        if analysis_id is not None:
            owner = await self._session.get(Analysis, analysis_id)
            if owner is not None:
                await UsageService(self._session, get_settings()).record_provider_call(
                    owner.user_id, estimated_cost
                )
        status_name = getattr(status, "value", str(status))
        registry.record_provider_call(
            provider=row.provider,
            operation=row.operation,
            status=status_name,
            seconds=latency_ms / 1000 if latency_ms is not None else None,
        )
        log.log(
            logging.WARNING if status == ProviderCallStatus.FAILED else logging.INFO,
            "provider call",
            extra={
                "analysis_id": str(analysis_id) if analysis_id else "",
                "provider": row.provider,
                "operation": row.operation,
                "status": status_name,
                "latency_ms": latency_ms,
                "cost": estimated_cost,
                # Only the error *code* is safe to log; messages may quote provider payloads.
                "error_code": (error or {}).get("code") if error else None,
            },
        )
        return row

    @asynccontextmanager
    async def track(
        self,
        *,
        analysis_id: uuid.UUID | None,
        provider: str,
        operation: str,
        request_hash: str | None = None,
    ) -> AsyncIterator[CallOutcome]:
        """Time a provider call and persist its outcome, including failures and timeouts.

        Usage::

            async with recorder.track(...) as call:
                result = await provider.detect(...)
                call.model_version = result.model_version
                call.response = {...}
        """
        outcome = CallOutcome()
        started = time.perf_counter()
        try:
            yield outcome
        except TimeoutError as exc:
            await self.record(
                analysis_id=analysis_id,
                provider=provider,
                operation=operation,
                status=ProviderCallStatus.TIMEOUT,
                latency_ms=int((time.perf_counter() - started) * 1000),
                request_hash=request_hash,
                model_version=outcome.model_version,
                error={"type": type(exc).__name__, "message": str(exc)[:MAX_ERROR_MESSAGE]},
            )
            raise
        except Exception as exc:
            await self.record(
                analysis_id=analysis_id,
                provider=provider,
                operation=operation,
                status=ProviderCallStatus.FAILED,
                latency_ms=int((time.perf_counter() - started) * 1000),
                request_hash=request_hash,
                model_version=outcome.model_version,
                error={
                    "type": type(exc).__name__,
                    "message": str(exc)[:MAX_ERROR_MESSAGE],
                    **outcome.extra_error,
                },
            )
            raise
        await self.record(
            analysis_id=analysis_id,
            provider=provider,
            operation=operation,
            status=outcome.status,
            latency_ms=int((time.perf_counter() - started) * 1000),
            request_hash=request_hash,
            model_version=outcome.model_version,
            request_id=outcome.request_id,
            estimated_cost=outcome.estimated_cost,
            response=outcome.response,
        )
