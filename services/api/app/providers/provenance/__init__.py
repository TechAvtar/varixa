"""C2PA / Content Credentials inspection engines behind one interface."""

from app.config import Settings
from app.providers.provenance.base import (
    NullProvenanceInspector,
    ProvenanceInspectionError,
    ProvenanceInspector,
    RawProvenance,
)
from app.providers.provenance.c2patool import C2paToolInspector, find_c2patool


def build_provenance_inspector(settings: Settings) -> ProvenanceInspector:
    engine = settings.provenance_engine
    if engine in ("auto", "c2patool"):
        exe = find_c2patool(settings.c2patool_path)
        if exe:
            return C2paToolInspector(
                exe,
                temp_dir=settings.data_dir / "tmp",
                timeout_seconds=settings.c2patool_timeout_seconds,
            )
        if engine == "c2patool":
            raise RuntimeError("VERIXA_PROVENANCE_ENGINE=c2patool but c2patool was not found")
    return NullProvenanceInspector()


__all__ = [
    "C2paToolInspector",
    "NullProvenanceInspector",
    "ProvenanceInspectionError",
    "ProvenanceInspector",
    "RawProvenance",
    "build_provenance_inspector",
    "find_c2patool",
]
