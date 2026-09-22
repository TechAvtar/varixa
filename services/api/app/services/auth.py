"""Authentication: registration, login, refresh-token rotation, logout, token resolution.

Security properties:
- passwords stored as Argon2id hashes only
- refresh tokens stored as SHA-256 only, rotated on every use, revocable
- access tokens are short-lived JWTs bound to a session, so logout is immediate
- login failures never reveal whether the email exists
- failed logins and registrations are throttled per email and per client address
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import User, UserSession
from app.repositories.user import UserRepository
from app.repositories.user_session import UserSessionRepository
from app.utils import security
from app.utils.errors import ConflictError, RateLimitedError, UnauthorizedError
from app.utils.ratelimit import SlidingWindowLimiter

INVALID_CREDENTIALS = "Invalid email or password."
TOO_MANY_ATTEMPTS = "Too many attempts. Please try again later."
INVALID_SESSION = "Session is invalid or has expired."
INVALID_TOKEN = "Invalid or expired access token."


@dataclass(frozen=True)
class IssuedTokens:
    access_token: str
    refresh_token: str
    expires_in: int


def _as_utc(dt: datetime) -> datetime:
    # SQLite returns naive datetimes for timezone-aware columns; treat them as UTC.
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


@dataclass(frozen=True)
class AuthLimiters:
    """Process-wide attempt counters shared by every request (kept on ``app.state``)."""

    login: SlidingWindowLimiter  # failed attempts per email
    login_ip: SlidingWindowLimiter  # failed attempts per client address (shared NATs: higher)
    register: SlidingWindowLimiter

    @classmethod
    def from_settings(cls, settings: Settings) -> "AuthLimiters":
        window = settings.login_window_minutes * 60
        return cls(
            login=SlidingWindowLimiter(limit=settings.login_max_attempts, window_seconds=window),
            login_ip=SlidingWindowLimiter(
                limit=settings.login_max_attempts_per_ip, window_seconds=window
            ),
            register=SlidingWindowLimiter(
                limit=settings.register_max_per_hour, window_seconds=3600
            ),
        )


def _throttle(limiter: SlidingWindowLimiter, *keys: str) -> None:
    for key in keys:
        decision = limiter.check(key)
        if not decision.allowed:
            raise RateLimitedError(TOO_MANY_ATTEMPTS, retry_after=decision.retry_after)


class AuthService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        *,
        limiters: AuthLimiters | None = None,
    ) -> None:
        self._db = session
        self._settings = settings
        self._users = UserRepository(session)
        self._sessions = UserSessionRepository(session)
        self._limiters = limiters or AuthLimiters.from_settings(settings)

    # -- registration / login -------------------------------------------------

    async def register(
        self, *, email: str, password: str, name: str | None, client_ip: str = "unknown"
    ) -> User:
        normalized = email.strip().lower()
        ip_key = f"ip:{client_ip}"
        _throttle(self._limiters.register, ip_key)
        self._limiters.register.hit(ip_key)  # every attempt counts, successful or not
        if await self._users.get_by_email(normalized) is not None:
            raise ConflictError("An account with this email already exists.", code="EMAIL_TAKEN")
        user = User(email=normalized, name=name, password_hash=security.hash_password(password))
        await self._users.add(user)
        await self._db.commit()
        return user

    async def login(self, *, email: str, password: str, client_ip: str = "unknown") -> IssuedTokens:
        normalized = email.strip().lower()
        email_key, ip_key = f"email:{normalized}", f"ip:{client_ip}"
        # Checked before the password so a locked account cannot be probed at all.
        _throttle(self._limiters.login, email_key)
        _throttle(self._limiters.login_ip, ip_key)
        user = await self._users.get_by_email(normalized)
        if user is None or user.password_hash is None:
            # Run a hash verify anyway to keep timing similar for unknown emails.
            security.verify_password(password, security.hash_password("timing-equalizer"))
            self._record_failure(email_key, ip_key)
            raise UnauthorizedError(INVALID_CREDENTIALS, code="INVALID_CREDENTIALS")
        if not security.verify_password(password, user.password_hash):
            self._record_failure(email_key, ip_key)
            raise UnauthorizedError(INVALID_CREDENTIALS, code="INVALID_CREDENTIALS")
        self._limiters.login.reset(email_key)
        tokens = await self._start_session(user)
        await self._db.commit()
        return tokens

    # -- session lifecycle ----------------------------------------------------

    async def refresh(self, *, refresh_token: str) -> IssuedTokens:
        user_session = await self._sessions.get_by_token_hash(security.hash_token(refresh_token))
        now = datetime.now(UTC)
        if user_session is None or not self._is_active(user_session, now):
            raise UnauthorizedError(INVALID_SESSION, code="INVALID_SESSION")
        # Rotate: the presented token is now dead; issue a fresh one on the same session.
        new_refresh = security.generate_refresh_token()
        user_session.refresh_token_hash = security.hash_token(new_refresh)
        user_session.last_used_at = now
        user_session.expires_at = now + self._refresh_ttl
        access = self._access_token(user_session, now)
        await self._db.commit()
        return IssuedTokens(access, new_refresh, self._access_ttl_seconds)

    async def logout(self, *, session_id: uuid.UUID) -> None:
        user_session = await self._sessions.get(session_id)
        if user_session is not None and user_session.revoked_at is None:
            user_session.revoked_at = datetime.now(UTC)
            await self._db.commit()

    async def resolve_access_token(self, token: str) -> User:
        """Return the user for a valid access token bound to an active session."""
        try:
            user_id, session_id = security.decode_access_token(token, secret=self._secret)
        except security.InvalidTokenError as exc:
            raise UnauthorizedError(INVALID_TOKEN, code="INVALID_TOKEN") from exc
        user_session = await self._sessions.get(session_id)
        if (
            user_session is None
            or user_session.user_id != user_id
            or not self._is_active(user_session, datetime.now(UTC))
        ):
            raise UnauthorizedError(INVALID_SESSION, code="INVALID_SESSION")
        user = await self._users.get(user_id)
        if user is None:
            raise UnauthorizedError(INVALID_SESSION, code="INVALID_SESSION")
        return user

    # -- helpers ----------------------------------------------------------------

    def _record_failure(self, email_key: str, ip_key: str) -> None:
        self._limiters.login.hit(email_key)
        self._limiters.login_ip.hit(ip_key)

    async def _start_session(self, user: User) -> IssuedTokens:
        now = datetime.now(UTC)
        refresh = security.generate_refresh_token()
        user_session = UserSession(
            user_id=user.id,
            refresh_token_hash=security.hash_token(refresh),
            expires_at=now + self._refresh_ttl,
            last_used_at=now,
        )
        await self._sessions.add(user_session)
        return IssuedTokens(
            self._access_token(user_session, now), refresh, self._access_ttl_seconds
        )

    def _access_token(self, user_session: UserSession, now: datetime) -> str:
        return security.create_access_token(
            secret=self._secret,
            user_id=user_session.user_id,
            session_id=user_session.id,
            ttl=timedelta(minutes=self._settings.access_token_ttl_minutes),
            now=now,
        )

    @staticmethod
    def _is_active(user_session: UserSession, now: datetime) -> bool:
        return user_session.revoked_at is None and _as_utc(user_session.expires_at) > now

    @property
    def _secret(self) -> str:
        return self._settings.secret_key.get_secret_value()

    @property
    def _refresh_ttl(self) -> timedelta:
        return timedelta(days=self._settings.refresh_token_ttl_days)

    @property
    def _access_ttl_seconds(self) -> int:
        return self._settings.access_token_ttl_minutes * 60
