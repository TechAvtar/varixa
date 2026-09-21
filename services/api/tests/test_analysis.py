import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Analysis, AnalysisFile, User
from app.models.enums import AnalysisStatus, AnalysisType
from app.providers.storage.local import LocalObjectStorage
from app.services.analysis import AnalysisService
from app.utils.errors import ConflictError, NotFoundError
from tests.test_auth import bearer, login, register

Json = dict[str, Any]


# -- fixtures -------------------------------------------------------------------


@pytest.fixture
def storage(tmp_path: Any) -> LocalObjectStorage:
    return LocalObjectStorage(root=tmp_path / "s", secret="x" * 40, public_base_url="http://t")


@pytest.fixture
def service(session: AsyncSession, storage: LocalObjectStorage) -> AnalysisService:
    return AnalysisService(session, storage)


async def make_user(session: AsyncSession, email: str = "owner@example.com") -> User:
    user = User(email=email)
    session.add(user)
    await session.commit()
    return user


async def create_via_api(client: AsyncClient, email: str) -> tuple[Json, dict[str, str]]:
    """Register+login via API and create one analysis directly in the app's DB."""
    await register(client, email=email)
    tokens = await login(client, email=email)
    app = client._transport.app  # type: ignore[attr-defined]
    async with app.state.session_factory() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one()
        svc = AnalysisService(db, app.state.storage)
        analysis = await svc.create(user, type=AnalysisType.IMAGE, title="mine")
        return {"id": str(analysis.id), "user_id": str(user.id)}, bearer(tokens)


# -- service: lifecycle ---------------------------------------------------------


async def test_create_starts_queued(service: AnalysisService, session: AsyncSession) -> None:
    user = await make_user(session)
    a = await service.create(user, type=AnalysisType.TEXT, title="  ")
    assert a.status == AnalysisStatus.QUEUED
    assert a.title is None  # blank titles are normalised away
    assert a.user_id == user.id


async def test_happy_path_transitions(service: AnalysisService, session: AsyncSession) -> None:
    user = await make_user(session)
    a = await service.create(user, type=AnalysisType.IMAGE, title=None)
    await service.mark_processing(a)
    assert a.status == AnalysisStatus.PROCESSING
    await service.mark_completed(a)
    assert a.status == AnalysisStatus.COMPLETED
    assert a.completed_at is not None


async def test_failure_records_safe_error(service: AnalysisService, session: AsyncSession) -> None:
    user = await make_user(session)
    a = await service.create(user, type=AnalysisType.IMAGE, title=None)
    await service.mark_failed(a, code="INVALID_FILE", message="m" * 5000)
    assert a.status == AnalysisStatus.FAILED
    assert a.error_code == "INVALID_FILE"
    assert a.error_message is not None and len(a.error_message) == 1000


@pytest.mark.parametrize(
    ("setup", "attempt"),
    [
        ("queued", "completed"),  # must pass through processing
        ("completed", "processing"),  # terminal
        ("failed", "processing"),  # terminal
        ("completed", "failed"),
    ],
)
async def test_illegal_transitions_rejected(
    service: AnalysisService, session: AsyncSession, setup: str, attempt: str
) -> None:
    user = await make_user(session)
    a = await service.create(user, type=AnalysisType.IMAGE, title=None)
    if setup == "completed":
        await service.mark_processing(a)
        await service.mark_completed(a)
    elif setup == "failed":
        await service.mark_failed(a, code="X", message="x")

    with pytest.raises(ConflictError) as exc:
        if attempt == "completed":
            await service.mark_completed(a)
        elif attempt == "processing":
            await service.mark_processing(a)
        else:
            await service.mark_failed(a, code="X", message="x")
    assert exc.value.code == "INVALID_TRANSITION"


# -- service: ownership + deletion ---------------------------------------------


async def test_get_owned_hides_foreign_and_deleted(
    service: AnalysisService, session: AsyncSession
) -> None:
    owner = await make_user(session, "a@example.com")
    other = await make_user(session, "b@example.com")
    a = await service.create(owner, type=AnalysisType.IMAGE, title=None)

    assert (await service.get_owned(owner, a.id)).id == a.id
    with pytest.raises(NotFoundError):
        await service.get_owned(other, a.id)
    with pytest.raises(NotFoundError):
        await service.get_owned(owner, uuid.uuid4())

    await service.soft_delete(owner, a.id)
    with pytest.raises(NotFoundError):
        await service.get_owned(owner, a.id)
    with pytest.raises(NotFoundError):
        await service.soft_delete(owner, a.id)  # not idempotent by design: it is gone


async def test_soft_delete_removes_stored_files(
    service: AnalysisService, session: AsyncSession, storage: LocalObjectStorage
) -> None:
    user = await make_user(session)
    a = await service.create(user, type=AnalysisType.IMAGE, title=None)
    key = f"uploads/{user.id}/{a.id}/{'0' * 64}.jpg"
    await storage.put(key, b"jpeg", content_type="image/jpeg")
    session.add(AnalysisFile(analysis_id=a.id, object_key=key, sha256="0" * 64))
    await session.commit()
    session.expire_all()

    await service.soft_delete(user, a.id)

    assert not await storage.exists(key)
    row = (await session.execute(select(Analysis).where(Analysis.id == a.id))).scalar_one()
    assert row.deleted_at is not None  # record kept for audit; hidden from reads


async def test_list_and_counts_are_user_scoped(
    service: AnalysisService, session: AsyncSession
) -> None:
    a_user = await make_user(session, "a@example.com")
    b_user = await make_user(session, "b@example.com")
    for _ in range(3):
        await service.create(a_user, type=AnalysisType.IMAGE, title=None)
    await service.create(a_user, type=AnalysisType.TEXT, title=None)
    await service.create(b_user, type=AnalysisType.TEXT, title=None)

    items, total = await service.list_owned(a_user, page=1, page_size=2)
    assert total == 4 and len(items) == 2
    items, _ = await service.list_owned(a_user, page=2, page_size=2)
    assert len(items) == 2
    items, _ = await service.list_owned(a_user, page=3, page_size=2)
    assert items == []
    assert await service.counts(a_user) == {"total": 4, "image": 3, "text": 1}
    assert await service.counts(b_user) == {"total": 1, "image": 0, "text": 1}


# -- API ------------------------------------------------------------------------


async def test_api_requires_auth(client: AsyncClient) -> None:
    assert (await client.get("/analysis")).status_code == 401
    assert (await client.get(f"/analysis/{uuid.uuid4()}")).status_code == 401
    assert (await client.delete(f"/analysis/{uuid.uuid4()}")).status_code == 401


async def test_api_get_list_delete_flow(client: AsyncClient) -> None:
    created, headers = await create_via_api(client, "owner@example.com")

    r = await client.get(f"/analysis/{created['id']}", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == created["id"]
    assert body["status"] == "queued" and body["type"] == "image" and body["title"] == "mine"
    assert "user_id" not in body and "object_key" not in body

    r = await client.get("/analysis?page_size=5", headers=headers)
    assert r.status_code == 200
    assert r.json()["total"] == 1 and r.json()["items"][0]["id"] == created["id"]

    r = await client.get("/analysis/counts", headers=headers)
    assert r.json() == {"total": 1, "image": 1, "text": 0}

    r = await client.delete(f"/analysis/{created['id']}", headers=headers)
    assert r.status_code == 204
    r = await client.get(f"/analysis/{created['id']}", headers=headers)
    assert r.status_code == 404
    assert (await client.get("/analysis", headers=headers)).json()["total"] == 0


async def test_api_idor_returns_404_not_403(client: AsyncClient) -> None:
    created, _ = await create_via_api(client, "owner@example.com")
    _, intruder = await create_via_api(client, "intruder@example.com")

    r = await client.get(f"/analysis/{created['id']}", headers=intruder)
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"
    r = await client.delete(f"/analysis/{created['id']}", headers=intruder)
    assert r.status_code == 404
    # Intruder's own list does not include the victim's analysis.
    ids = [i["id"] for i in (await client.get("/analysis", headers=intruder)).json()["items"]]
    assert created["id"] not in ids


async def test_api_validates_pagination_and_ids(client: AsyncClient) -> None:
    _, headers = await create_via_api(client, "owner@example.com")
    assert (await client.get("/analysis?page=0", headers=headers)).status_code == 422
    assert (await client.get("/analysis?page_size=101", headers=headers)).status_code == 422
    r = await client.get("/analysis/not-a-uuid", headers=headers)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"
