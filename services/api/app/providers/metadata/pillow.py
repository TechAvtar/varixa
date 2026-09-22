"""Pillow fallback extractor: EXIF (incl. GPS/ExifIFD), ICC header, XMP. Reduced coverage.

Used when ExifTool is unavailable. Tag names follow ExifTool's so the
normaliser and consumers do not care which engine ran. MakerNotes and IPTC are
not decoded; the step records the engine so reports can state the limitation.
"""

import asyncio
import io
from typing import Any

import PIL
from PIL import ExifTags, Image, ImageCms

from app.providers.metadata.base import RawGroups, RawMetadata, cap_value

_SUB_IFDS = {
    ExifTags.IFD.Exif: ("ExifIFD", ExifTags.TAGS),
    ExifTags.IFD.GPSInfo: ("GPS", ExifTags.GPSTAGS),
    ExifTags.IFD.Interop: ("InteropIFD", ExifTags.TAGS),
}


def _plain(value: Any) -> Any:
    # IFDRational / tuples of rationals -> floats; bytes are summarised by cap_value.
    if hasattr(value, "numerator") and hasattr(value, "denominator"):
        try:
            return float(value)
        except (ZeroDivisionError, ValueError):
            return None
    if isinstance(value, tuple | list):
        return [_plain(v) for v in value]
    return cap_value(value)


class PillowExtractor:
    name = "pillow"

    async def extract(self, data: bytes) -> RawMetadata:
        return await asyncio.to_thread(self._extract_sync, data)

    def _extract_sync(self, data: bytes) -> RawMetadata:
        groups: RawGroups = {}
        warnings: list[str] = []
        with Image.open(io.BytesIO(data)) as img:
            groups["File"] = {
                "FileType": img.format or "",
                "ImageWidth": img.width,
                "ImageHeight": img.height,
                "ColorMode": img.mode,
            }
            try:
                exif = img.getexif()
            except Exception as exc:  # malformed EXIF must not break extraction
                exif = Image.Exif()
                warnings.append(f"EXIF unreadable: {type(exc).__name__}")
            if len(exif):
                groups["EXIF"] = {}
                for tag_id, value in exif.items():
                    if tag_id in _SUB_IFDS:
                        continue
                    name = ExifTags.TAGS.get(tag_id, f"Tag{tag_id:04X}")
                    groups["EXIF"][f"IFD0:{name}"] = _plain(value)
                for ifd, (label, table) in _SUB_IFDS.items():
                    try:
                        sub = exif.get_ifd(ifd)
                    except Exception as exc:
                        warnings.append(f"{label} unreadable: {type(exc).__name__}")
                        continue
                    for tag_id, value in sub.items():
                        name = table.get(tag_id, f"Tag{tag_id:04X}")
                        groups["EXIF"][f"{label}:{name}"] = _plain(value)

            icc = img.info.get("icc_profile")
            if icc:
                icc_group: dict[str, Any] = {"ProfileSize": len(icc)}
                try:
                    profile = ImageCms.ImageCmsProfile(io.BytesIO(icc)).profile
                    icc_group["ProfileDescription"] = profile.profile_description
                    icc_group["DeviceManufacturer"] = profile.manufacturer
                    icc_group["ColorSpaceData"] = profile.xcolor_space
                except Exception as exc:
                    warnings.append(f"ICC unreadable: {type(exc).__name__}")
                groups["ICC_Profile"] = icc_group

            try:
                xmp = img.getxmp()
            except Exception as exc:
                xmp = {}
                warnings.append(f"XMP unreadable: {type(exc).__name__}")
            if xmp:
                groups["XMP"] = {"xmpmeta": cap_value(xmp)}

        return RawMetadata(
            engine=self.name, engine_version=PIL.__version__, groups=groups, warnings=warnings
        )
