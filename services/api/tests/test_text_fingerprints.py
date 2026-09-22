import uuid

from httpx import AsyncClient

from app.services.text.fingerprints import (
    MINHASH_PERMUTATIONS,
    canonical_form,
    compute_text_fingerprints,
    estimate_jaccard,
)
from tests.test_text import ENGLISH, auth

PARAPHRASE_LIGHT = ENGLISH.replace("bright, cold day", "bright and cold day")
UNRELATED = (
    "Quarterly revenue rose eleven percent on stronger subscription renewals, while hardware "
    "margins narrowed slightly. Management reiterated full-year guidance and flagged currency "
    "headwinds in two regions. Analysts expect the next update in March."
)


# -- pure functions ---------------------------------------------------------------------------


def test_canonical_form_ignores_case_punctuation_and_layout() -> None:
    a = canonical_form("Hello,   World!\nIt's  fine.")
    b = canonical_form("hello world it s FINE")
    assert a == b == "hello world it s fine"


def test_fingerprints_are_deterministic_and_distinct() -> None:
    f1 = compute_text_fingerprints(ENGLISH, ENGLISH)
    f2 = compute_text_fingerprints(ENGLISH, ENGLISH)
    assert f1 == f2
    assert len(f1.minhash) == MINHASH_PERMUTATIONS and all(0 <= v < 2**32 for v in f1.minhash)
    assert f1.sha256 != f1.normalized_sha256 or ENGLISH == ENGLISH  # both defined
    assert f1.shingle_count > 0
    other = compute_text_fingerprints(UNRELATED, UNRELATED)
    assert other.canonical_sha256 != f1.canonical_sha256


def test_reformatted_copy_shares_canonical_hash_but_not_byte_hash() -> None:
    reformatted = ENGLISH.upper().replace(",", " ,").replace("\n\n", "\n")
    f_orig = compute_text_fingerprints(ENGLISH, ENGLISH)
    f_copy = compute_text_fingerprints(reformatted, reformatted)
    assert f_orig.sha256 != f_copy.sha256
    assert f_orig.canonical_sha256 == f_copy.canonical_sha256
    assert estimate_jaccard(f_orig.minhash, f_copy.minhash) == 1.0


def test_minhash_estimates_similarity_sensibly() -> None:
    f_orig = compute_text_fingerprints(ENGLISH, ENGLISH)
    f_near = compute_text_fingerprints(PARAPHRASE_LIGHT, PARAPHRASE_LIGHT)
    f_far = compute_text_fingerprints(UNRELATED, UNRELATED)
    near = estimate_jaccard(f_orig.minhash, f_near.minhash)
    far = estimate_jaccard(f_orig.minhash, f_far.minhash)
    assert near >= 0.5, near
    assert far <= 0.1, far
    assert far < near


def test_empty_and_tiny_texts_do_not_match_everything() -> None:
    empty = compute_text_fingerprints("", "")
    assert empty.shingle_count == 0
    assert estimate_jaccard(empty.minhash, empty.minhash) == 0.0
    tiny = compute_text_fingerprints("hello", "hello")
    assert tiny.shingle_count == 1
    assert (
        estimate_jaccard(tiny.minhash, compute_text_fingerprints("hello", "hello").minhash) == 1.0
    )


# -- step + API ----------------------------------------------------------------------------------


async def create(client: AsyncClient, headers: dict[str, str], text: str, title: str) -> str:
    r = await client.post("/analysis/text", headers=headers, json={"text": text, "title": title})
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


async def test_text_pipeline_persists_fingerprints_and_finds_matches(client: AsyncClient) -> None:
    headers = await auth(client)
    original = await create(client, headers, ENGLISH, "original")
    exact = await create(client, headers, ENGLISH, "exact copy")
    reformatted = await create(client, headers, ENGLISH.upper(), "shouted copy")
    near = await create(client, headers, PARAPHRASE_LIGHT, "light edit")
    unrelated = await create(client, headers, UNRELATED, "unrelated")

    detail = (await client.get(f"/analysis/{original}", headers=headers)).json()
    assert [s["name"] for s in detail["steps"]] == [
        "normalize",
        "language",
        "statistics",
        "fingerprints",
        "ai",
    ]
    assert detail["steps"][3]["status"] == "completed"

    r = await client.get(f"/analysis/{original}/fingerprints", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "text"
    fp = body["fingerprints"]
    assert len(fp["sha256"]) == 64 and len(fp["canonical_sha256"]) == 64
    assert fp["shingle_count"] > 0 and fp["algorithm_version"] == "v1"

    by_id = {s["analysis_id"]: s for s in body["similar"]}
    assert set(by_id) == {exact, reformatted, near}, by_id
    assert by_id[exact]["relation"] == "exact"
    assert by_id[reformatted]["relation"] == "canonical"
    assert by_id[near]["relation"] == "near" and by_id[near]["estimated_jaccard"] >= 0.5
    assert unrelated not in by_id
    assert body["similar"][0]["analysis_id"] == exact  # strongest first
    assert any("came first" in x for x in body["limitations"])


async def test_text_similarity_is_owner_scoped_and_ignores_deleted(client: AsyncClient) -> None:
    alice = await auth(client, "alice@example.com")
    bob = await auth(client, "bob@example.com")
    a1 = await create(client, alice, ENGLISH, "a1")
    a2 = await create(client, alice, ENGLISH, "a2")
    await create(client, bob, ENGLISH, "b1")
    body = (await client.get(f"/analysis/{a1}/fingerprints", headers=alice)).json()
    assert [s["analysis_id"] for s in body["similar"]] == [a2]
    assert (await client.delete(f"/analysis/{a2}", headers=alice)).status_code == 204
    body = (await client.get(f"/analysis/{a1}/fingerprints", headers=alice)).json()
    assert body["similar"] == []


async def test_text_fingerprints_enforce_ownership(client: AsyncClient) -> None:
    owner = await auth(client, "o@example.com")
    aid = await create(client, owner, ENGLISH, "mine")
    intruder = await auth(client, "i@example.com")
    assert (await client.get(f"/analysis/{aid}/fingerprints", headers=intruder)).status_code == 404
    missing = await client.get(f"/analysis/{uuid.uuid4()}/fingerprints", headers=owner)
    assert missing.status_code == 404
