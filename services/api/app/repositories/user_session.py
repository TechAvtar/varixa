import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import UserSession


class UserSessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, session_id: uuid.UUID) -> UserSession | None:
        return await self._session.get(UserSession, session_id)

    async def get_by_token_hash(self, token_hash: str) -> UserSession | None:
        stmt = select(UserSession).where(UserSession.refresh_token_hash == token_hash)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def add(self, user_session: UserSession) -> UserSession:
        self._session.add(user_session)
        await self._session.flush()
        return user_session
