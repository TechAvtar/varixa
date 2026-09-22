"""Metadata extraction engines behind one interface (ExifTool preferred, Pillow fallback)."""

from app.config import Settings
from app.providers.metadata.base import (
    MetadataExtractionError,
    MetadataExtractor,
    RawMetadata,
)
from app.providers.metadata.exiftool import ExifToolExtractor, find_exiftool
from app.providers.metadata.pillow import PillowExtractor


def build_metadata_extractor(settings: Settings) -> MetadataExtractor:
    engine = settings.metadata_engine
    if engine in ("auto", "exiftool"):
        exe = find_exiftool(settings.exiftool_path)
        if exe:
            return ExifToolExtractor(exe, timeout_seconds=settings.exiftool_timeout_seconds)
        if engine == "exiftool":
            raise RuntimeError("VERIXA_METADATA_ENGINE=exiftool but ExifTool was not found")
    return PillowExtractor()


__all__ = [
    "ExifToolExtractor",
    "MetadataExtractionError",
    "MetadataExtractor",
    "PillowExtractor",
    "RawMetadata",
    "build_metadata_extractor",
    "find_exiftool",
]
