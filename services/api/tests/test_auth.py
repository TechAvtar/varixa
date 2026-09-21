import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient

from app.config import Settings
from app.utils import security

EMAIL = "analyst@example.com"
PASSWORD = "correct horse battery"


Json = dict[str, Any]


async def register(client: AsyncClient, email: str = EMAIL, password: str = PASSWORD) -> Json:
    r = await client.post("/auth/register", json={"email": email, "password": password})
    assert r.status_code == 201, r.text
    body: Json = r.json()
    return body


async def login(client: AsyncClient, email: str = EMAIL, password: str = PASSWORD) -> Json:
    r = await client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    body: Json = r.json()
    return body


def bearer(tokens: Json) -> dict[str, str]:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


# -- registration ---------------------------------------------------------------


async def test_register_returns_user_without_secrets(client: AsyncClient) -> None:
    body = await register(client)
    assert body["email"] == EMAIL
    assert body["role"] == "user"
    assert "password" not in body and "password_hash" not in body


async def test_register_duplicate_email_conflicts(client: AsyncClient) -> None:
    await register(client)
    r = await client.post("/auth/register", json={"email": EMAIL.upper(), "password": PASSWORD})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "EMAIL_TAKEN"


@pytest.mark.parametrize("password", ["short", "x" * 129])
async def test_register_rejects_bad_password_length(client: AsyncClient, password: str) -> None:
    r = await client.post("/auth/register", json={"email": EMAIL, "password": password})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_register_rejects_invalid_email(client: AsyncClient) -> None:
    r = await client.post("/auth/register", json={"email": "nope", "password": PASSWORD})
    assert r.status_code == 422


# -- login ----------------------------------------------------------------------


async def test_login_issues_token_pair(client: AsyncClient) -> None:
    await register(client)
    tokens = await login(client)
    assert tokens["token_type"] == "bearer"
    assert tokens["expires_in"] > 0
    assert tokens["access_token"] and tokens["refresh_token"]


@pytest.mark.parametrize(
    ("email", "password"),
    [(EMAIL, "wrong password!"), ("nobody@example.com", PASSWORD)],
)
async def test_login_failures_are_indistinguishable(
    client: AsyncClient, email: str, password: str
) -> None:
    await register(client)
    r = await client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 401
    assert r.json()["error"] == {
        "code": "INVALID_CREDENTIALS",
        "message": "Invalid email or password.",
        "request_id": r.headers["X-Request-ID"],
    }


# -- current user ---------------------------------------------------------------


async def test_me_requires_bearer(client: AsyncClient) -> None:
    r = await client.get("/auth/me")
    assert r.status_code == 401
    assert r.headers["WWW-Authenticate"] == "Bearer"
    assert r.json()["error"]["code"] == "AUTH_REQUIRED"


async def test_me_returns_current_user(client: AsyncClient) -> None:
    await register(client)
    tokens = await login(client)
    r = await client.get("/auth/me", headers=bearer(tokens))
    assert r.status_code == 200
    assert r.json()["email"] == EMAIL


async def test_tampered_token_rejected(client: AsyncClient) -> None:
    await register(client)
    tokens = await login(client)
    forged = tokens["access_token"][:-4] + "abcd"
    r = await client.get("/auth/me", headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "INVALID_TOKEN"


async def test_token_signed_with_other_secret_rejected(
    client: AsyncClient, migrated_settings: Settings
) -> None:
    await register(client)
    tokens = await login(client)
    user_id, session_id = security.decode_access_token(
        tokens["access_token"], secret=migrated_settings.secret_key.get_secret_value()
    )
    forged = security.create_access_token(
        secret="another-secret-of-sufficient-length-1234",
        user_id=user_id,
        session_id=session_id,
        ttl=timedelta(minutes=5),
    )
    r = await client.get("/auth/me", headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 401


async def test_expired_access_token_rejected(
    client: AsyncClient, migrated_settings: Settings
) -> None:
    await register(client)
    tokens = await login(client)
    secret = migrated_settings.secret_key.get_secret_value()
    user_id, session_id = security.decode_access_token(tokens["access_token"], secret=secret)
    expired = security.create_access_token(
        secret=secret,
        user_id=user_id,
        session_id=session_id,
        ttl=timedelta(minutes=5),
        now=datetime.now(UTC) - timedelta(hours=1),
    )
    r = await client.get("/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert r.status_code == 401


async def test_token_for_unknown_session_rejected(
    client: AsyncClient, migrated_settings: Settings
) -> None:
    body = await register(client)
    token = security.create_access_token(
        secret=migrated_settings.secret_key.get_secret_value(),
        user_id=uuid.UUID(body["id"]),
        session_id=uuid.uuid4(),
        ttl=timedelta(minutes=5),
    )
    r = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "INVALID_SESSION"


# -- refresh / logout -----------------------------------------------------------


async def test_refresh_rotates_tokens(client: AsyncClient) -> None:
    await register(client)
    first = await login(client)
    r = await client.post("/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert r.status_code == 200
    second = r.json()
    assert second["refresh_token"] != first["refresh_token"]

    # Old refresh token is dead after rotation.
    r = await client.post("/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "INVALID_SESSION"

    # New access token works.
    r = await client.get("/auth/me", headers=bearer(second))
    assert r.status_code == 200


async def test_logout_revokes_session_immediately(client: AsyncClient) -> None:
    await register(client)
    tokens = await login(client)
    r = await client.post("/auth/logout", headers=bearer(tokens))
    assert r.status_code == 204

    r = await client.get("/auth/me", headers=bearer(tokens))
    assert r.status_code == 401
    r = await client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 401


async def test_sessions_are_independent(client: AsyncClient) -> None:
    await register(client)
    a = await login(client)
    b = await login(client)
    assert (await client.post("/auth/logout", headers=bearer(a))).status_code == 204
    assert (await client.get("/auth/me", headers=bearer(b))).status_code == 200


# -- error envelope -------------------------------------------------------------


async def test_request_id_is_echoed_and_present_in_errors(client: AsyncClient) -> None:
    r = await client.get("/auth/me", headers={"X-Request-ID": "trace-123"})
    assert r.headers["X-Request-ID"] == "trace-123"
    assert r.json()["error"]["request_id"] == "trace-123"


async def test_unknown_route_uses_error_envelope(client: AsyncClient) -> None:
    r = await client.get("/does-not-exist")
    assert r.status_code == 404
    assert set(r.json()["error"]) == {"code", "message", "request_id"}
