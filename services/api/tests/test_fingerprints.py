import uuid
from pathlib import Path
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import ImageFingerprints
from app.providers.storage.local import LocalObjectStorage
from app.services.analysis.steps import HashImageStep, ValidateImageStep
from app.services.image.similarity import compare
from tests.test_image_upload import auth_headers, make_image
from tests.test_pipeline import make_ctx

FIXTURES = Path(__file__).parent / "fixtures"
Json = dict[str, Any]


class FP:
    def __init__(self, sha256: str, phash: str, dhash: str, ahash: str) -> None:
        self.sha256, self.phash, self.dhash, self.ahash = sha256, phash, dhash, ahash


# -- pure comparison ------------------------------------------------------------------------


def test_compare_exact_and_near_and_none() -> None:
    a = FP("s1", "0" * 16, "0" * 16, "0" * 16)
    exact = compare(a, FP("s1", "f" * 16, "f" * 16, "f" * 16), near_threshold=10)
    assert exact is not None and exact.relation == "exact"
    near = compare(a, FP("s2", "0000000000000003", "f" * 16, "0" * 16), near_threshold=10)
    assert near is not None and near.relation == "near" and near.phash_distance == 2
    assert near.dhash_distance == 64 and not near.sha256_match
    assert compare(a, FP("s3", "f" * 16, "f" * 16, "f" * 16), near_threshold=10) is None
    assert (
        compare(a, FP("s4", "00000000000007ff", "f" * 16, "0" * 16), near_threshold=10) is None
    )  # 11 bits


# -- persistence + idempotency ------------------------------------------------------------------


async def upload(client: AsyncClient, headers: dict[str, str], name: str, data: bytes) -> str:
    r = await client.post(
        "/analysis/image", headers=headers, files={"file": (name, data, "image/png")}
    )
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


async def test_hash_step_persists_and_is_idempotent(
    session: AsyncSession, migrated_settings: Settings, tmp_path: Path
) -> None:
    storage = LocalObjectStorage(root=tmp_path / "s", secret="x" * 40, public_base_url="http://t")
    ctx = await make_ctx(session, storage, migrated_settings, with_file=True)
    await ValidateImageStep().run(ctx)
    first = await HashImageStep().run(ctx)
    second = await HashImageStep().run(ctx)  # recompute must not duplicate
    await session.commit()
    rows = (
        (
            await session.execute(
                select(ImageFingerprints).where(ImageFingerprints.analysis_id == ctx.analysis.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].phash == first.details["phash"] == second.details["phash"]
    assert rows[0].sha256 == ctx.file.sha256  # type: ignore[union-attr]
    assert rows[0].algorithm_version == "v1"


# -- API ----------------------------------------------------------------------------------------


async def test_fingerprints_endpoint_and_similarity(client: AsyncClient) -> None:
    headers = await auth_headers(client)
    original = await upload(client, headers, "g.png", (FIXTURES / "gradient.png").read_bytes())
    recompressed = await upload(
        client, headers, "g.jpg", (FIXTURES / "gradient_q60.jpg").read_bytes()
    )
    duplicate = await upload(client, headers, "g2.png", (FIXTURES / "gradient.png").read_bytes())
    unrelated = await upload(client, headers, "b.png", (FIXTURES / "black.png").read_bytes())

    r = await client.get(f"/analysis/{original}/fingerprints", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    fp = body["fingerprints"]
    assert len(fp["sha256"]) == 64 and len(fp["md5"]) == 32 and len(fp["phash"]) == 16
    assert body["near_threshold"] >= 1

    by_id = {s["analysis_id"]: s for s in body["similar"]}
    assert set(by_id) == {recompressed, duplicate}, by_id
    assert by_id[duplicate]["relation"] == "exact" and by_id[duplicate]["sha256_match"]
    assert by_id[recompressed]["relation"] == "near"
    assert by_id[recompressed]["phash_distance"] <= 4
    assert unrelated not in by_id
    # Exact duplicates are listed first.
    assert body["similar"][0]["analysis_id"] == duplicate
    assert any("which came first" in x or "origin" in x for x in body["limitations"])


async def test_similarity_is_scoped_to_the_owner(client: AsyncClient) -> None:
    alice = await auth_headers(client, "alice@example.com")
    bob = await auth_headers(client, "bob@example.com")
    data = (FIXTURES / "gradient.png").read_bytes()
    a_id = await upload(client, alice, "a.png", data)
    await upload(client, bob, "b.png", data)  # identical bytes, different user

    body = (await client.get(f"/analysis/{a_id}/fingerprints", headers=alice)).json()
    assert body["similar"] == []  # Bob's copy must never surface for Alice


async def test_deleted_analyses_do_not_match(client: AsyncClient) -> None:
    headers = await auth_headers(client)
    data = make_image("PNG", (50, 40))
    keep = await upload(client, headers, "k.png", data)
    gone = await upload(client, headers, "g.png", data)
    assert (await client.delete(f"/analysis/{gone}", headers=headers)).status_code == 204
    body = (await client.get(f"/analysis/{keep}/fingerprints", headers=headers)).json()
    assert body["similar"] == []


async def test_fingerprints_endpoint_enforces_ownership(client: AsyncClient) -> None:
    owner = await auth_headers(client, "owner@example.com")
    aid = await upload(client, owner, "a.png", make_image("PNG"))
    intruder = await auth_headers(client, "intruder@example.com")
    assert (await client.get(f"/analysis/{aid}/fingerprints", headers=intruder)).status_code == 404
    missing = await client.get(f"/analysis/{uuid.uuid4()}/fingerprints", headers=owner)
    assert missing.status_code == 404
    assert (await client.get(f"/analysis/{aid}/fingerprints")).status_code == 401
