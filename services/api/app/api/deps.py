"""Shared FastAPI dependencies for the HTTP layer."""

import uuid
from typing import Annotated

from fastapi import BackgroundTasks, Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.database import get_session
from app.models import User
from app.providers.storage.base import ObjectStorage
from app.services.analysis import AnalysisService
from app.services.auth import AuthService
from app.services.reports.service import ReportService
from app.services.usage import UsageService
from app.utils import security
from app.utils.errors import UnauthorizedError
from app.workers import BackgroundTaskDispatcher, Dispatcher

_bearer = HTTPBearer(auto_error=False)

DbSession = Annotated[AsyncSession, Depends(get_session)]
AppSettings = Annotated[Settings, Depends(get_settings)]


def get_storage(request: Request) -> ObjectStorage:
    storage: ObjectStorage = request.app.state.storage
    return storage


Storage = Annotated[ObjectStorage, Depends(get_storage)]


def get_dispatcher(
    request: Request, tasks: BackgroundTasks, storage: Storage, settings: AppSettings
) -> Dispatcher:
    override: Dispatcher | None = getattr(request.app.state, "dispatcher", None)
    return override or BackgroundTaskDispatcher(
        tasks, request.app.state.session_factory, storage, settings
    )


Jobs = Annotated[Dispatcher, Depends(get_dispatcher)]


def get_auth_service(session: DbSession, settings: AppSettings) -> AuthService:
    return AuthService(session, settings)


AuthSvc = Annotated[AuthService, Depends(get_auth_service)]


def get_analysis_service(
    session: DbSession, storage: Storage, settings: AppSettings
) -> AnalysisService:
    return AnalysisService(session, storage, settings)


AnalysisSvc = Annotated[AnalysisService, Depends(get_analysis_service)]


def get_report_service(
    session: DbSession, storage: Storage, settings: AppSettings
) -> ReportService:
    return ReportService(session, storage, settings)


ReportSvc = Annotated[ReportService, Depends(get_report_service)]


def get_usage_service(session: DbSession, settings: AppSettings) -> UsageService:
    return UsageService(session, settings)


UsageSvc = Annotated[UsageService, Depends(get_usage_service)]


def _bearer_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer" or not credentials.credentials:
        raise UnauthorizedError("Authentication required.", code="AUTH_REQUIRED")
    return credentials.credentials


BearerToken = Annotated[str, Depends(_bearer_token)]


async def get_current_user(token: BearerToken, auth: AuthSvc, request: Request) -> User:
    user = await auth.resolve_access_token(token)
    request.state.user_id = user.id
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_current_session_id(token: BearerToken, settings: AppSettings) -> uuid.UUID:
    """Session id from an already-validated bearer token (use after CurrentUser)."""
    try:
        _, session_id = security.decode_access_token(
            token, secret=settings.secret_key.get_secret_value()
        )
    except security.InvalidTokenError as exc:
        raise UnauthorizedError("Invalid or expired access token.", code="INVALID_TOKEN") from exc
    return session_id


CurrentSessionId = Annotated[uuid.UUID, Depends(get_current_session_id)]
