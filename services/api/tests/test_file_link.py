import uuid

from httpx import AsyncClient

from app.config import Settings
from tests.test_image_upload import auth_headers, make_image
from tests.test_text import ENGLISH


async def test_file_link_serves_the_original_to_its_owner_only(
    client: AsyncClient, migrated_settings: Settings
) -> None:
    owner = await auth_headers(client, "o@example.com")
    data = make_image("PNG", (40, 30))
    r = await client.post(
        "/analysis/image", headers=owner, files={"file": ("orig.png", data, "image/png")}
    )
    aid = r.json()["id"]

    link = (await client.get(f"/analysis/{aid}/file", headers=owner)).json()
    assert link["url"].startswith("http") and "sig=" in link["url"]
    assert "object_key" not in link and "uploads/" in link["url"]
    assert (link["width"], link["height"], link["mime_type"]) == (40, 30, "image/png")
    assert link["expires_in_seconds"] == migrated_settings.signed_url_ttl_seconds

    served = await client.get(link["url"])  # no auth header: the signature is the credential
    assert served.status_code == 200 and served.content == data
    assert served.headers["content-type"].startswith("image/png")

    intruder = await auth_headers(client, "i@example.com")
    assert (await client.get(f"/analysis/{aid}/file", headers=intruder)).status_code == 404
    assert (await client.get(f"/analysis/{uuid.uuid4()}/file", headers=owner)).status_code == 404
    assert (await client.get(f"/analysis/{aid}/file")).status_code == 401


async def test_tampered_or_expired_signature_is_rejected(
    client: AsyncClient, migrated_settings: Settings
) -> None:
    owner = await auth_headers(client)
    r = await client.post(
        "/analysis/image",
        headers=owner,
        files={"file": ("a.png", make_image("PNG"), "image/png")},
    )
    url = (await client.get(f"/analysis/{r.json()['id']}/file", headers=owner)).json()["url"]
    sig = url.split("sig=")[1][:64]
    flipped = ("0" if sig[0] != "0" else "1") + sig[1:]  # same length, wrong value
    bad = url.replace(sig, flipped)
    assert (await client.get(bad)).status_code == 403
    expired = url.replace("exp=", "exp=1")
    assert (await client.get(expired)).status_code == 403


async def test_text_analysis_file_link_exists_but_is_plain_text(
    client: AsyncClient, migrated_settings: Settings
) -> None:
    owner = await auth_headers(client)
    r = await client.post("/analysis/text", headers=owner, json={"text": ENGLISH})
    link = (await client.get(f"/analysis/{r.json()['id']}/file", headers=owner)).json()
    assert link["width"] is None and link["height"] is None
    served = await client.get(link["url"])
    assert served.status_code == 200 and served.headers["content-type"].startswith("text/plain")
