import io
import uuid
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from PIL import Image

from app.providers.metadata import (
    ExifToolExtractor,
    PillowExtractor,
    build_metadata_extractor,
    find_exiftool,
)
from app.providers.metadata.base import RawMetadata, cap_value
from app.services.image.metadata import (
    normalize_metadata,
    parse_exif_datetime,
    to_utc_or_none,
)
from tests.test_image_upload import auth_headers, make_image

EXIFTOOL = find_exiftool()
needs_exiftool = pytest.mark.skipif(EXIFTOOL is None, reason="exiftool not installed")


def jpeg_with_exif() -> bytes:
    img = Image.new("RGB", (40, 30), (10, 20, 30))
    exif = Image.Exif()
    exif[0x010F] = "Canon"
    exif[0x0110] = "Canon EOS R5"
    exif[0x0131] = "Adobe Photoshop 25.0"
    exif[0x0112] = 6
    exif[0x0132] = "2024:05:01 10:20:30"
    exif[0x8769] = {0x9003: "2024:04:30 18:05:02", 0x9011: "+02:00", 0xA434: "RF 50mm F1.2"}
    exif[0x8825] = {1: "N", 2: (51.0, 30.0, 0.0), 3: "E", 4: (0.0, 7.0, 0.0)}
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif.tobytes(), quality=90)
    return buf.getvalue()


# -- parsing -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "offset", "expected", "tz_known"),
    [
        ("2024:04:30 18:05:02", None, datetime(2024, 4, 30, 18, 5, 2), False),
        (
            "2024:04:30 18:05:02",
            "+02:00",
            datetime(2024, 4, 30, 18, 5, 2, tzinfo=timezone(timedelta(hours=2))),
            True,
        ),
        (
            "2024:04:30 18:05:02+02:00",
            None,
            datetime(2024, 4, 30, 18, 5, 2, tzinfo=timezone(timedelta(hours=2))),
            True,
        ),
        (
            "2024-04-30T18:05:02.250Z",
            None,
            datetime(2024, 4, 30, 18, 5, 2, 250000, tzinfo=UTC),
            True,
        ),
        (
            "2024:04:30 18:05:02",
            "-05:30",
            datetime(2024, 4, 30, 18, 5, 2, tzinfo=timezone(-timedelta(hours=5, minutes=30))),
            True,
        ),
    ],
)
def test_parse_exif_datetime(
    value: str, offset: str | None, expected: datetime, tz_known: bool
) -> None:
    ts = parse_exif_datetime(value, offset)
    assert ts is not None and ts.raw == value
    assert ts.parsed == expected and ts.tz_known is tz_known


@pytest.mark.parametrize("value", ["0000:00:00 00:00:00", "not a date", "2024:13:45 99:99:99", ""])
def test_parse_exif_datetime_keeps_raw_when_unparseable(value: str) -> None:
    ts = parse_exif_datetime(value)
    assert ts is not None and ts.parsed is None and ts.raw == value


def test_parse_exif_datetime_none() -> None:
    assert parse_exif_datetime(None) is None


def test_to_utc_only_for_timezone_known() -> None:
    assert to_utc_or_none(parse_exif_datetime("2024:04:30 18:05:02")) is None
    utc = to_utc_or_none(parse_exif_datetime("2024:04:30 18:05:02", "+02:00"))
    assert utc == datetime(2024, 4, 30, 16, 5, 2, tzinfo=UTC)


def test_cap_value_bounds_sizes() -> None:
    assert cap_value("x" * 5000).startswith("x" * 4096) and "truncated" in cap_value("x" * 5000)
    assert cap_value(b"\x00" * 10) == "(Binary data 10 bytes)"
    assert len(cap_value(list(range(1000)))) == 256


# -- normalisation (engine independent) -------------------------------------------------


def test_normalize_from_exiftool_shaped_groups() -> None:
    raw = RawMetadata(
        engine="exiftool",
        engine_version="13.59",
        groups={
            "EXIF": {
                "IFD0:Make": "Canon",
                "IFD0:Model": "Canon EOS R5",
                "IFD0:Software": "Adobe Photoshop 25.0",
                "IFD0:Orientation": 6,
                "IFD0:ModifyDate": "2024:05:01 10:20:30",
                "ExifIFD:DateTimeOriginal": "2024:04:30 18:05:02",
                "ExifIFD:OffsetTimeOriginal": "+02:00",
                "ExifIFD:LensModel": "RF 50mm F1.2",
                "GPS:GPSLatitude": 51.5,
            },
            "ICC_Profile": {"ICC-header:ProfileDescription": "sRGB IEC61966-2.1"},
            "File": {"ImageWidth": 40, "ImageHeight": 30},
        },
        warnings=["Warning: something minor"],
    )
    n = normalize_metadata(raw)
    assert (n.camera_make, n.camera_model, n.lens) == ("Canon", "Canon EOS R5", "RF 50mm F1.2")
    assert n.software == "Adobe Photoshop 25.0"
    assert n.orientation == 6 and n.orientation_label == "Rotate 90 CW"
    assert n.captured_at is not None and n.captured_at.tz_known and n.captured_at.parsed is not None
    assert n.captured_at.parsed.utcoffset() == timedelta(hours=2)
    assert n.modified_at is not None and not n.modified_at.tz_known
    assert n.gps_present is True
    assert n.color_profile == "sRGB IEC61966-2.1"
    assert (n.image_width, n.image_height) == (40, 30)
    assert n.has_exif and n.has_icc and not n.has_xmp and not n.has_iptc
    assert n.tag_counts == {"EXIF": 9, "ICC_Profile": 1, "File": 2}
    assert n.warnings == ["Warning: something minor"]
    json = n.to_json()
    assert json["captured_at"] == {
        "raw": "2024:04:30 18:05:02",
        "parsed": "2024-04-30T18:05:02+02:00",
        "tz_known": True,
    }


def test_normalize_empty_metadata_is_all_unknown() -> None:
    n = normalize_metadata(
        RawMetadata(engine="pillow", engine_version="12", groups={"File": {"FileType": "PNG"}})
    )
    assert not n.has_exif and n.camera_make is None and n.captured_at is None and not n.gps_present


# -- extractors ----------------------------------------------------------------------------


async def test_pillow_extractor_reads_exif_gps_and_normalises() -> None:
    raw = await PillowExtractor().extract(jpeg_with_exif())
    assert raw.engine == "pillow"
    assert raw.get("EXIF", "Make") == "Canon"
    assert raw.get("EXIF", "LensModel") == "RF 50mm F1.2"
    assert raw.get("EXIF", "GPSLatitudeRef") == "N"
    n = normalize_metadata(raw)
    assert n.camera_model == "Canon EOS R5" and n.gps_present and n.orientation == 6
    assert n.captured_at is not None and n.captured_at.tz_known


async def test_pillow_extractor_handles_image_without_metadata() -> None:
    raw = await PillowExtractor().extract(make_image("PNG"))
    assert "EXIF" not in raw.groups and raw.group("File")["FileType"] == "PNG"


@needs_exiftool
async def test_exiftool_extractor_reads_groups() -> None:
    assert EXIFTOOL is not None
    ext = ExifToolExtractor(EXIFTOOL)
    raw = await ext.extract(jpeg_with_exif())
    assert raw.engine == "exiftool" and raw.engine_version[0].isdigit()
    assert raw.get("EXIF", "Make") == "Canon"
    assert raw.get("EXIF", "OffsetTimeOriginal") == "+02:00"
    assert raw.get("Composite", "GPSLatitude") == pytest.approx(51.5)
    assert not any(k.startswith("System:") for k in raw.group("File"))  # no filesystem noise
    n = normalize_metadata(raw)
    assert n.captured_at is not None and n.captured_at.tz_known and n.lens == "RF 50mm F1.2"


@needs_exiftool
async def test_exiftool_extractor_survives_garbage_input() -> None:
    assert EXIFTOOL is not None
    raw = await ExifToolExtractor(EXIFTOOL).extract(b"\xff\xd8\xff" + b"\x00" * 64)
    assert raw.engine == "exiftool"  # ExifTool reports what it can; no exception


def test_build_extractor_respects_engine_setting(migrated_settings: Any) -> None:
    migrated_settings.metadata_engine = "pillow"
    assert build_metadata_extractor(migrated_settings).name == "pillow"
    if EXIFTOOL:
        migrated_settings.metadata_engine = "auto"
        assert build_metadata_extractor(migrated_settings).name == "exiftool"


# -- step + API ------------------------------------------------------------------------------


async def test_upload_persists_metadata_and_endpoint_returns_it(client: AsyncClient) -> None:
    headers = await auth_headers(client)
    r = await client.post(
        "/analysis/image",
        headers=headers,
        files={"file": ("cam.jpg", jpeg_with_exif(), "image/jpeg")},
    )
    analysis_id = r.json()["id"]
    detail = (await client.get(f"/analysis/{analysis_id}", headers=headers)).json()
    step = next(s for s in detail["steps"] if s["name"] == "metadata")
    assert step["status"] == "completed"
    assert step["details"]["engine"] in ("exiftool", "pillow")

    r = await client.get(f"/analysis/{analysis_id}/metadata", headers=headers)
    assert r.status_code == 200
    body = r.json()
    n = body["normalized"]
    assert n["camera_make"] == "Canon" and n["software"] == "Adobe Photoshop 25.0"
    assert n["gps_present"] is True
    assert n["captured_at"]["parsed"] == "2024-04-30T18:05:02+02:00"
    assert any(k.endswith("Make") for k in body["exif"])
    assert isinstance(body["limitations"], list)


async def test_metadata_endpoint_for_image_without_metadata(client: AsyncClient) -> None:
    headers = await auth_headers(client)
    r = await client.post(
        "/analysis/image",
        headers=headers,
        files={"file": ("plain.png", make_image("PNG"), "image/png")},
    )
    body = (await client.get(f"/analysis/{r.json()['id']}/metadata", headers=headers)).json()
    assert body["normalized"]["has_exif"] is False and body["exif"] == {}
    assert any("does not" in lim for lim in body["limitations"])


async def test_metadata_endpoint_enforces_ownership(client: AsyncClient) -> None:
    owner = await auth_headers(client, "owner@example.com")
    r = await client.post(
        "/analysis/image", headers=owner, files={"file": ("a.png", make_image("PNG"), "image/png")}
    )
    intruder = await auth_headers(client, "intruder@example.com")
    assert (
        await client.get(f"/analysis/{r.json()['id']}/metadata", headers=intruder)
    ).status_code == 404
    assert (
        await client.get(f"/analysis/{uuid.uuid4()}/metadata", headers=owner)
    ).status_code == 404
    assert (await client.get(f"/analysis/{r.json()['id']}/metadata")).status_code == 401
