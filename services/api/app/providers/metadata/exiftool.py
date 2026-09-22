"""ExifTool adapter: the preferred engine (EXIF, XMP, IPTC, ICC, MakerNotes, ...).

The image is passed on stdin with a fixed argument list, so no user-controlled
string ever reaches the command line. Output is JSON grouped by family 0:1
(e.g. ``EXIF:IFD0:Make``); binary blobs are summarised by ExifTool itself.
"""

import asyncio
import json
import shutil
from pathlib import Path

from app.providers.metadata.base import (
    MAX_TAGS,
    MetadataExtractionError,
    RawGroups,
    RawMetadata,
    cap_value,
)

_ARGS = ["-j", "-G0:1", "-n", "-a", "-struct", "-fast2", "-charset", "utf8", "-"]
_MAX_OUTPUT = 8 * 1024 * 1024

# Family-0 groups that describe the local filesystem entry, not the content.
_DROP_GROUPS = {"SourceFile"}
_DROP_PREFIXES = ("File:System:",)

_WINDOWS_CANDIDATES = (
    Path.home() / "AppData/Local/Programs/ExifTool/ExifTool.exe",
    Path("C:/Program Files/ExifTool/exiftool.exe"),
)


def find_exiftool(configured: str | None = None) -> str | None:
    """Resolve the ExifTool executable: explicit path, PATH lookup, then known installs."""
    if configured:
        return configured if Path(configured).is_file() or shutil.which(configured) else None
    found = shutil.which("exiftool")
    if found:
        return found
    for candidate in _WINDOWS_CANDIDATES:
        if candidate.is_file():
            return str(candidate)
    return None


class ExifToolExtractor:
    name = "exiftool"

    def __init__(self, executable: str, *, timeout_seconds: float = 30.0) -> None:
        self._exe = executable
        self._timeout = timeout_seconds

    async def version(self) -> str:
        out, _ = await self._run(["-ver"], b"")
        return out.decode("ascii", "replace").strip()

    async def extract(self, data: bytes) -> RawMetadata:
        stdout, stderr = await self._run(_ARGS, data)
        try:
            payload = json.loads(stdout.decode("utf-8", "replace"))
        except json.JSONDecodeError as exc:
            raise MetadataExtractionError("exiftool returned invalid JSON") from exc
        if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
            raise MetadataExtractionError("exiftool returned no record")

        record: dict[str, object] = payload[0]
        version = str(record.get("ExifTool:ExifToolVersion", "unknown"))
        groups: RawGroups = {}
        count = 0
        for key, value in record.items():
            if key in _DROP_GROUPS or key.startswith(_DROP_PREFIXES):
                continue
            family0, _, rest = key.partition(":")
            if not rest:
                continue
            count += 1
            if count > MAX_TAGS:
                break
            groups.setdefault(family0, {})[rest] = cap_value(value)

        warnings = [
            line.strip()
            for line in stderr.decode("utf-8", "replace").splitlines()
            if line.strip().startswith("Warning:")
        ]
        return RawMetadata(
            engine=self.name, engine_version=version, groups=groups, warnings=warnings
        )

    async def _run(self, args: list[str], stdin: bytes) -> tuple[bytes, bytes]:
        try:
            proc = await asyncio.create_subprocess_exec(
                self._exe,
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            raise MetadataExtractionError("exiftool could not be started") from exc
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(stdin), self._timeout)
        except TimeoutError as exc:
            proc.kill()
            await proc.wait()
            raise MetadataExtractionError("exiftool timed out") from exc
        if len(stdout) > _MAX_OUTPUT:
            raise MetadataExtractionError("exiftool output exceeded the size limit")
        # ExifTool exits 1 for files with errors but still prints what it could read.
        if proc.returncode not in (0, 1):
            raise MetadataExtractionError(f"exiftool exited with status {proc.returncode}")
        return stdout, stderr
