"""Password hashing and token primitives. Pure functions; no I/O."""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError

_hasher = PasswordHasher()
JWT_ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError):
        return False


def generate_refresh_token() -> str:
    """Opaque, URL-safe, 256-bit random token. Only its hash is stored."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_access_token(
    *,
    secret: str,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    ttl: timedelta,
    now: datetime | None = None,
) -> str:
    issued = now or datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "sid": str(session_id),
        "type": "access",
        "iat": int(issued.timestamp()),
        "exp": int((issued + ttl).timestamp()),
    }
    return jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)


class InvalidTokenError(Exception):
    pass


def decode_access_token(token: str, *, secret: str) -> tuple[uuid.UUID, uuid.UUID]:
    """Return (user_id, session_id) or raise InvalidTokenError. Never leaks why."""
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            secret,
            algorithms=[JWT_ALGORITHM],
            options={"require": ["sub", "sid", "exp", "iat", "type"]},
        )
        if payload.get("type") != "access":
            raise InvalidTokenError
        return uuid.UUID(payload["sub"]), uuid.UUID(payload["sid"])
    except (jwt.PyJWTError, ValueError, TypeError) as exc:
        raise InvalidTokenError from exc
