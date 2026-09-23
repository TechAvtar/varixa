"""Declared lineage: generator markers, IPTC digital source type, XMP edit history."""

import io
from types import SimpleNamespace as Row
from typing import Any

import pytest
from httpx import AsyncClient
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from app.providers.metadata.base import RawMetadata
from app.providers.metadata.exiftool import ExifToolExtractor, find_exiftool
from app.providers.metadata.pillow import PillowExtractor
from app.services.evidence.engine import Observations, build_evidence
from app.services.evidence.timeline import build_timeline
from app.services.image.lineage import extract_lineage, generator_signals, xmp_properties
from app.services.image.metadata import normalize_metadata
from tests.test_evidence_engine import T, by_rule, rules
from tests.test_image_upload import auth_headers

EXIFTOOL = find_exiftool()
needs_exiftool = pytest.mark.skipif(EXIFTOOL is None, reason="exiftool not installed")

A1111 = (
    "a cat on a mat\nNegative prompt: dog\n"
    "Steps: 20, Sampler: Euler a, CFG scale: 7, Seed: 1, Size: 512x512, Model: sd_xl"
)

XMP_HISTORY = (
    b'<?xpacket begin="\xef\xbb\xbf" id="W5M0MpCehiHzreSzNTczkc9d"?>'
    b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF '
    b'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"><rdf:Description rdf:about="" '
    b'xmlns:xmp="http://ns.adobe.com/xap/1.0/" xmlns:xmpMM="http://ns.adobe.com/xap/1.0/mm/" '
    b'xmlns:stEvt="http://ns.adobe.com/xap/1.0/sType/ResourceEvent#" '
    b'xmlns:stRef="http://ns.adobe.com/xap/1.0/sType/ResourceRef#" '
    b'xmlns:Iptc4xmpExt="http://iptc.org/std/Iptc4xmpExt/2008-02-29/" '
    b'xmp:CreatorTool="Adobe Photoshop 25.0" xmpMM:DocumentID="xmp.did:AAA" '
    b'xmpMM:InstanceID="xmp.iid:BBB" xmpMM:OriginalDocumentID="xmp.did:000" '
    b'Iptc4xmpExt:DigitalSourceType="http://cv.iptc.org/newscodes/digitalsourcetype/'
    b'trainedAlgorithmicMedia">'
    b'<xmpMM:DerivedFrom stRef:documentID="xmp.did:000" stRef:instanceID="xmp.iid:111"/>'
    b"<xmpMM:History><rdf:Seq>"
    b'<rdf:li stEvt:action="created" stEvt:instanceID="xmp.iid:111" '
    b'stEvt:when="2024-04-30T18:10:00+02:00" stEvt:softwareAgent="Adobe Photoshop 25.0"/>'
    b'<rdf:li stEvt:action="saved" stEvt:instanceID="xmp.iid:BBB" '
    b'stEvt:when="2024-05-01T10:20:30+02:00" stEvt:softwareAgent="Adobe Photoshop 25.0" '
    b'stEvt:changed="/"/>'
    b"</rdf:Seq></xmpMM:History></rdf:Description></rdf:RDF></x:xmpmeta>"
    b'<?xpacket end="w"?>'
)


def png_with_parameters(text: str = A1111, key: str = "parameters") -> bytes:
    img = Image.new("RGB", (32, 32), (1, 2, 3))
    info = PngInfo()
    info.add_text(key, text)
    buf = io.BytesIO()
    img.save(buf, format="PNG", pnginfo=info)
    return buf.getvalue()


def jpeg_with_xmp_history() -> bytes:
    img = Image.new("RGB", (32, 32), (4, 5, 6))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", xmp=XMP_HISTORY)
    return buf.getvalue()


# -- generator markers -----------------------------------------------------------------------------
async def test_pillow_reads_png_chunks_and_detects_a1111_parameters() -> None:
    raw = await PillowExtractor().extract(png_with_parameters())
    assert raw.get("PNG", "Parameters") is not None
    signals = generator_signals(raw)
    assert [s.generator for s in signals] == ["Stable Diffusion WebUI"]
    assert signals[0].tag == "PNG:Parameters" and "Steps: 20" in signals[0].excerpt
    n = normalize_metadata(raw)
    assert n.generator == "Stable Diffusion WebUI" and len(n.generator_signals) == 1


@needs_exiftool
async def test_exiftool_reads_png_chunks_the_same_way() -> None:
    assert EXIFTOOL is not None
    raw = await ExifToolExtractor(EXIFTOOL).extract(png_with_parameters())
    n = normalize_metadata(raw)
    assert n.generator == "Stable Diffusion WebUI"
    assert n.generator_signals[0]["tag"] == "PNG:Parameters"


@pytest.mark.parametrize(
    ("groups", "expected"),
    [
        ({"PNG": {"PNG:Prompt": '{"3": {"class_type": "KSampler"}}'}}, "ComfyUI"),
        (
            {"PNG": {"PNG:Comment": '{"steps": 28, "sampler": "k_euler", "uc": "bad"}'}},
            "unspecified AI generator",
        ),
        ({"PNG": {"PNG:Software": "NovelAI"}}, "NovelAI"),
        ({"EXIF": {"IFD0:Software": "ComfyUI 0.3"}}, "ComfyUI"),
        ({"XMP": {"XMP-xmp:CreatorTool": "Adobe Firefly 3"}}, "Adobe Firefly"),
        ({"XMP": {"XMP-dc:Description": {"x-default": "Job ID 12 - Midjourney v6"}}}, "Midjourney"),
        ({"EXIF": {"IFD0:Software": "Adobe Photoshop 25.0"}}, None),
        ({"PNG": {"PNG:Comment": "Taken at the beach"}}, None),
    ],
)
def test_generator_markers_across_tags(groups: dict[str, Any], expected: str | None) -> None:
    raw = RawMetadata(engine="exiftool", engine_version="x", groups=groups)
    n = normalize_metadata(raw)
    assert n.generator == expected


# -- XMP lineage -----------------------------------------------------------------------------------
async def test_pillow_xmp_history_is_flattened_and_parsed() -> None:
    raw = await PillowExtractor().extract(jpeg_with_xmp_history())
    props = xmp_properties(raw)
    assert props["CreatorTool"] == "Adobe Photoshop 25.0"
    lineage = extract_lineage(raw)
    assert lineage.digital_source_type == "trainedAlgorithmicMedia"
    assert lineage.declares_algorithmic_source
    assert lineage.document_id == "xmp.did:AAA" and lineage.original_document_id == "xmp.did:000"
    assert lineage.derived_from_document_id == "xmp.did:000"
    assert [e.action for e in lineage.edit_history] == ["created", "saved"]
    assert lineage.edit_history[1].software == "Adobe Photoshop 25.0"
    assert lineage.edit_history[1].when == "2024-05-01T10:20:30+02:00"
    n = normalize_metadata(raw)
    assert n.software == "Adobe Photoshop 25.0"  # creator tool fills in when EXIF has none
    assert n.generator is None  # Photoshop is an editor, not a generator


@needs_exiftool
async def test_exiftool_xmp_history_yields_the_same_lineage() -> None:
    assert EXIFTOOL is not None
    raw = await ExifToolExtractor(EXIFTOOL).extract(jpeg_with_xmp_history())
    lineage = extract_lineage(raw)
    assert lineage.digital_source_type == "trainedAlgorithmicMedia"
    assert [e.action for e in lineage.edit_history] == ["created", "saved"]
    assert lineage.derived_from_document_id == "xmp.did:000"
    assert lineage.edit_history[0].when == "2024:04:30 18:10:00+02:00"


# -- evidence and timeline -------------------------------------------------------------------------
def _meta(**normalized: Any) -> Any:
    return Row(
        engine="exiftool",
        engine_version="13",
        software=None,
        camera_make=None,
        camera_model=None,
        normalized_json={"has_exif": True, "has_xmp": True, "has_iptc": False, **normalized},
    )


def test_generator_and_source_type_rules_are_strong_but_capped() -> None:
    meta = _meta(
        generator="Stable Diffusion WebUI",
        generator_signals=[
            {"generator": "Stable Diffusion WebUI", "tag": "PNG:Parameters", "excerpt": "Steps: 20"}
        ],
        digital_source_type="trainedAlgorithmicMedia",
    )
    drafts = build_evidence(Observations("image", metadata=meta), T)
    gen = by_rule(drafts, "metadata.generator")
    assert gen.level == "STRONG" and "Stable Diffusion WebUI" in gen.claim
    assert gen.data["tags"] == ["PNG:Parameters"] and "prove" in (gen.limitation or "")
    src = by_rule(drafts, "metadata.source-type")
    assert src.level == "STRONG" and "as declared" in src.claim
    capture = _meta(digital_source_type="digitalCapture")
    d = by_rule(build_evidence(Observations("image", metadata=capture), T), "metadata.source-type")
    assert d.level == "POSSIBLE" and d.data["algorithmic"] is False


def test_edit_history_rule_and_timeline_events() -> None:
    meta = _meta(
        document_id="xmp.did:AAA",
        original_document_id="xmp.did:000",
        derived_from_document_id="xmp.did:000",
        edit_history=[
            {
                "action": "created",
                "software": "Adobe Photoshop 25.0",
                "when": "2024:04:30 18:10:00+02:00",
                "changed": None,
                "instance_id": "xmp.iid:111",
            },
            {
                "action": "saved",
                "software": "Adobe Photoshop 25.0",
                "when": "2024:05:01 10:20:30+02:00",
                "changed": "/",
                "instance_id": "xmp.iid:BBB",
            },
            {
                "action": "converted",
                "software": None,
                "when": None,
                "changed": None,
                "instance_id": None,
            },
        ],
    )
    o = Observations("image", metadata=meta)
    drafts = build_evidence(o, T)
    d = by_rule(drafts, "metadata.edit-history")
    assert d.level == "STRONG" and "3 actions" in d.claim and "Adobe Photoshop 25.0" in d.claim
    assert "derived from another document" in d.claim
    assert d.data["actions"] == ["created", "saved", "converted"]
    events = [e for e in build_timeline(o, drafts) if e.event_type == "metadata.edit"]
    assert len(events) == 3
    assert events[0].event_time is not None and events[0].tz_known
    assert events[2].event_time is None and events[2].raw_time is None
    assert all(e.source_rules == ["metadata.edit-history"] for e in events)
    assert "metadata.edit-history" not in rules(
        build_evidence(Observations("image", metadata=_meta()), T)
    )


async def test_upload_surfaces_lineage_in_metadata_evidence_and_timeline(
    client: AsyncClient,
) -> None:
    headers = await auth_headers(client)
    r = await client.post(
        "/analysis/image",
        headers=headers,
        files={"file": ("gen.png", png_with_parameters(), "image/png")},
    )
    aid = r.json()["id"]
    n = (await client.get(f"/analysis/{aid}/metadata", headers=headers)).json()["normalized"]
    assert n["generator"] == "Stable Diffusion WebUI"
    evidence = (await client.get(f"/analysis/{aid}/evidence", headers=headers)).json()["items"]
    gen = next(e for e in evidence if e["rule"] == "metadata.generator")
    assert gen["level"] == "STRONG"
    assert "metadata.none" not in {e["rule"] for e in evidence}  # chunks are metadata

    r = await client.post(
        "/analysis/image",
        headers=headers,
        files={"file": ("edited.jpg", jpeg_with_xmp_history(), "image/jpeg")},
    )
    aid = r.json()["id"]
    n = (await client.get(f"/analysis/{aid}/metadata", headers=headers)).json()["normalized"]
    assert [e["action"] for e in n["edit_history"]] == ["created", "saved"]
    assert n["digital_source_type"] == "trainedAlgorithmicMedia"
    evidence = (await client.get(f"/analysis/{aid}/evidence", headers=headers)).json()["items"]
    assert {e["rule"] for e in evidence} >= {"metadata.edit-history", "metadata.source-type"}
    timeline = (await client.get(f"/analysis/{aid}/timeline", headers=headers)).json()["events"]
    edits = [e for e in timeline if e["event_type"] == "metadata.edit"]
    assert len(edits) == 2 and all(e["tz_known"] for e in edits)
