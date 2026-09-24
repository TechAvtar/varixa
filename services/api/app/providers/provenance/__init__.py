"""C2PA / Content Credentials inspection engines behind one interface."""

from app.config import Settings
from app.providers.provenance.base import (
    NullProvenanceInspector,
    ProvenanceInspectionError,
    ProvenanceInspector,
    RawProvenance,
)
from app.providers.provenance.c2patool import (
    SETTINGS_FILE,
    C2paToolInspector,
    TrustFiles,
    bundled_trust_files,
    file_version,
    find_c2patool,
)


def trust_files_for(settings: Settings) -> TrustFiles | None:
    """Trust material for the engine's trust run, from settings. None = trust not evaluated."""
    mode = settings.c2pa_trust_mode
    if mode == "off":
        return None
    if mode == "bundled":
        return bundled_trust_files()
    anchors = settings.c2pa_trust_anchors_path
    allowed = settings.c2pa_allowed_list_path
    config = settings.c2pa_trust_config_path
    versioned = anchors or allowed
    return TrustFiles(
        mode="custom",
        anchors=anchors,
        allowed_list=allowed,
        trust_config=config,
        list_version=file_version(versioned) if versioned else None,
    )


def trust_summary(settings: Settings) -> dict[str, str | None]:
    """Non-sensitive facts for /health: the mode and the list version, never paths."""
    files = trust_files_for(settings)
    return {
        "mode": settings.c2pa_trust_mode,
        "list_version": files.list_version if files else None,
    }


def build_provenance_inspector(settings: Settings) -> ProvenanceInspector:
    engine = settings.provenance_engine
    if engine in ("auto", "c2patool"):
        exe = find_c2patool(settings.c2patool_path)
        if exe:
            return C2paToolInspector(
                exe,
                temp_dir=settings.data_dir / "tmp",
                timeout_seconds=settings.c2patool_timeout_seconds,
                # Our settings file switches the engine's own network fetching off; only an
                # explicit opt-in (never in production, see preflight) leaves the defaults.
                settings_file=None if settings.c2pa_remote_manifest_fetch else SETTINGS_FILE,
                trust=trust_files_for(settings),
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
    "TrustFiles",
    "build_provenance_inspector",
    "find_c2patool",
    "trust_files_for",
    "trust_summary",
]
