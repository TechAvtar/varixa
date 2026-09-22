import uuid
from typing import Any

from httpx import AsyncClient

from app.services.text import (
    compute_statistics,
    compute_structure,
    detect_language,
    normalize_text,
)
from tests.test_auth import bearer, login, register

Json = dict[str, Any]

ENGLISH = (
    "The quick brown fox jumps over the lazy dog. It was a bright, cold day in April, and the "
    "clocks were striking thirteen! Was anyone watching? Nobody was watching.\n\n"
    "A second paragraph follows here. The quick brown fox jumps over the lazy dog."
)
FRENCH = (
    "Le renard brun rapide saute par-dessus le chien paresseux. C'était une journée claire et "
    "froide d'avril, et les horloges sonnaient treize heures."
)


async def auth(client: AsyncClient, email: str = "t@example.com") -> dict[str, str]:
    await register(client, email=email)
    return bearer(await login(client, email=email))


# -- normalisation -----------------------------------------------------------------------------


def test_normalize_is_conservative_and_reports_changes() -> None:
    raw = "Line one\r\nLine two  \r\n\r\n\r\n\r\nLine​three here‮\x07"
    out = normalize_text(raw)
    assert out.original == raw  # never altered
    assert out.normalized == "Line one\nLine two\n\nLinethree here"
    r = out.report
    assert r.changed and r.crlf_replaced == 5
    assert r.zero_width_removed == 1 and r.zero_width_kinds == ["ZERO WIDTH SPACE"]
    assert r.bidi_controls_removed == 1 and r.control_chars_removed == 1
    assert r.special_spaces_replaced == 1 and r.trailing_whitespace_lines == 1
    assert r.blank_runs_collapsed == 1


def test_normalize_nfc_and_no_change() -> None:
    decomposed = "é"  # e + combining acute
    out = normalize_text(decomposed)
    assert out.normalized == "é" and out.report.changed
    clean = normalize_text("plain text")
    assert not clean.report.changed and clean.normalized == "plain text"


# -- statistics ----------------------------------------------------------------------------------


def test_statistics_on_known_text() -> None:
    st = compute_statistics(ENGLISH)
    assert st.paragraph_count == 2
    assert st.sentence_count == 6
    assert st.word_count == 43
    assert st.unique_word_count < st.word_count and 0 < st.type_token_ratio < 1
    assert st.repeated_sentence_count == 1  # the fox sentence appears twice
    assert st.longest_sentence_words >= st.avg_sentence_length_words >= st.shortest_sentence_words
    assert st.punctuation_counts["."] == 4 and st.punctuation_counts["!"] == 1
    assert st.punctuation_counts["?"] == 1 and st.punctuation_counts[","] == 2
    assert any(t["phrase"] == "the quick brown" and t["count"] == 2 for t in st.repeated_trigrams)
    assert st.url_count == 0 and st.email_count == 0 and st.emoji_count == 0
    assert 0 < st.uppercase_ratio < 0.2


def test_statistics_handles_edge_cases() -> None:
    assert compute_statistics("").word_count == 0
    st = compute_statistics("Contact me@example.com or https://example.org now 🙂")
    assert st.email_count == 1 and st.url_count == 1 and st.emoji_count == 1
    assert st.sentence_count == 1


def test_structure_detection() -> None:
    text = "# Title\n\n- one\n- two\n1. first\n2) second\n\nBody paragraph here."
    s = compute_structure(text)
    assert s.markdown_headings == 1 and s.starts_with_heading
    assert s.bullet_lines == 2 and s.numbered_lines == 2
    assert s.has_multiple_paragraphs and s.blank_line_count == 2


# -- language -------------------------------------------------------------------------------------


def test_language_detection_is_probabilistic_and_deterministic() -> None:
    en = detect_language(ENGLISH)
    fr = detect_language(FRENCH)
    assert en.language == "en" and en.confidence is not None and 0 < en.confidence <= 1
    assert fr.language == "fr"
    assert detect_language(ENGLISH) == en  # seeded detector
    short = detect_language("hi")
    assert short.language is None and short.reason and "characters" in short.reason
    assert detect_language("1234 5678 !!!").language is None


# -- API ----------------------------------------------------------------------------------


async def test_create_text_analysis_runs_pipeline(client: AsyncClient) -> None:
    headers = await auth(client)
    r = await client.post(
        "/analysis/text", headers=headers, json={"text": ENGLISH, "title": " Essay "}
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["type"] == "text" and body["status"] == "queued"

    detail = (await client.get(f"/analysis/{body['id']}", headers=headers)).json()
    assert detail["status"] == "completed" and detail["title"] == "Essay"
    assert [s["name"] for s in detail["steps"]] == [
        "normalize",
        "language",
        "statistics",
        "fingerprints",
        "ai",
        "search",
        "evidence",
        "synthesis",
    ]
    assert all(s["status"] == "completed" for s in detail["steps"][:4])
    assert detail["steps"][4]["status"] == "skipped"  # no detector configured
    assert detail["steps"][5]["status"] == "skipped"  # no search provider configured
    assert detail["file"]["mime_type"] == "text/plain" and detail["file"]["size_bytes"] == len(
        ENGLISH.encode()
    )

    r = await client.get(f"/analysis/{body['id']}/text", headers=headers)
    assert r.status_code == 200, r.text
    t = r.json()
    assert t["language"]["language"] == "en"
    assert t["statistics"]["word_count"] == 43 and t["statistics"]["paragraph_count"] == 2
    assert t["original_excerpt"].startswith("The quick") and not t["truncated"]
    assert len(t["normalized_sha256"]) == 64 and t["original_sha256"] == detail["file"]["sha256"]
    assert any("not proof" in x or "cannot" in x for x in t["limitations"])


async def test_text_title_defaults_to_first_line(client: AsyncClient) -> None:
    headers = await auth(client)
    r = await client.post(
        "/analysis/text",
        headers=headers,
        json={"text": "A short headline\n\nThen the body text follows."},
    )
    detail = (await client.get(f"/analysis/{r.json()['id']}", headers=headers)).json()
    assert detail["title"] == "A short headline"


async def test_text_validation(client: AsyncClient) -> None:
    headers = await auth(client)
    assert (
        await client.post("/analysis/text", headers=headers, json={"text": ""})
    ).status_code == 422
    assert (
        await client.post("/analysis/text", headers=headers, json={"text": "   \n  "})
    ).status_code == 422
    big = "word " * 60_000  # 300k chars > test cap
    r = await client.post("/analysis/text", headers=headers, json={"text": big})
    assert r.status_code == 413 and r.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"
    assert (await client.post("/analysis/text", json={"text": ENGLISH})).status_code == 401


async def test_text_endpoint_enforces_ownership(client: AsyncClient) -> None:
    owner = await auth(client, "o@example.com")
    r = await client.post("/analysis/text", headers=owner, json={"text": ENGLISH})
    aid = r.json()["id"]
    intruder = await auth(client, "i@example.com")
    assert (await client.get(f"/analysis/{aid}/text", headers=intruder)).status_code == 404
    assert (await client.get(f"/analysis/{uuid.uuid4()}/text", headers=owner)).status_code == 404
    # Image endpoints answer 404 for a text analysis (nothing to return), never 500.
    assert (await client.get(f"/analysis/{aid}/metadata", headers=owner)).status_code == 404


async def test_hidden_characters_are_preserved_in_original_and_reported(
    client: AsyncClient,
) -> None:
    headers = await auth(client)
    text = "Visible​ text with‮ hidden marks. " * 3
    r = await client.post("/analysis/text", headers=headers, json={"text": text})
    t = (await client.get(f"/analysis/{r.json()['id']}/text", headers=headers)).json()
    assert t["normalization"]["zero_width_removed"] == 3
    assert t["normalization"]["bidi_controls_removed"] == 3
    assert "​" in t["original_excerpt"] and "​" not in t["normalized_excerpt"]
