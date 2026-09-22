"""c2patool adapter (Content Authenticity Initiative reference CLI).

c2patool only reads files, so the verified bytes are written to a private temp
file with a random name and the *validated* extension, then removed. Two runs:
the summary (manifest store) and ``-d`` (detailed, includes validation_status).
"""

import asyncio
import json
import shutil
import uuid
from pathlib import Path
from typing import Any

from app.providers.provenance.base import ProvenanceInspectionError, RawProvenance

_MAX_OUTPUT = 16 * 1024 * 1024
_NO_CLAIM_MARKERS = ("No claim found", "no claim found", "no manifest")
# Only extensions c2patool understands for the formats Verixa accepts; anything else -> "bin".
_SAFE_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "tif", "tiff"}

_WINDOWS_CANDIDATES = (
    Path.home() / "AppData/Local/Programs/c2patool/c2patool/c2patool.exe",
    Path.home() / "AppData/Local/Programs/c2patool/c2patool.exe",
)


def find_c2patool(configured: str | None = None) -> str | None:
    if configured:
        return configured if Path(configured).is_file() or shutil.which(configured) else None
    found = shutil.which("c2patool")
    if found:
        return found
    for candidate in _WINDOWS_CANDIDATES:
        if candidate.is_file():
            return str(candidate)
    return None


class C2paToolInspector:
    name = "c2patool"

    def __init__(self, executable: str, *, temp_dir: Path, timeout_seconds: float = 30.0) -> None:
        self._exe = executable
        self._temp_dir = temp_dir
        self._timeout = timeout_seconds

    async def version(self) -> str:
        out, _, _ = await self._run(["--version"])
        return out.decode("ascii", "replace").strip().removeprefix("c2patool ").strip()

    async def inspect(self, data: bytes, *, extension: str) -> RawProvenance:
        ext = extension.lower().lstrip(".")
        if ext not in _SAFE_EXTENSIONS:
            ext = "bin"
        self._temp_dir.mkdir(parents=True, exist_ok=True)
        path = self._temp_dir / f"c2pa-{uuid.uuid4().hex}.{ext}"
        try:
            await asyncio.to_thread(path.write_bytes, data)
            version = await self.version()
            summary_out, summary_err, rc = await self._run([str(path)])
            summary_text = summary_out.decode("utf-8", "replace")
            err_text = summary_err.decode("utf-8", "replace")
            if any(marker in summary_text + err_text for marker in _NO_CLAIM_MARKERS):
                return RawProvenance(engine=self.name, engine_version=version, present=False)
            if rc != 0 and not summary_text.lstrip().startswith("{"):
                first = next((ln.strip() for ln in err_text.splitlines() if ln.strip()), "")
                raise ProvenanceInspectionError(
                    f"c2patool could not read the file: {first[:200] or 'unknown error'}"
                )
            summary = _parse_json(summary_text, "summary")

            detailed_out, detailed_err, _ = await self._run([str(path), "-d"])
            detailed = _parse_json(detailed_out.decode("utf-8", "replace"), "detailed")
            status = detailed.get("validation_status") or []
            warnings = [
                line.strip()
                for line in (summary_err + detailed_err).decode("utf-8", "replace").splitlines()
                if line.strip()
            ]
            return RawProvenance(
                engine=self.name,
                engine_version=version,
                present=True,
                summary=summary,
                detailed=detailed,
                validation_status=[s for s in status if isinstance(s, dict)],
                warnings=warnings[:50],
            )
        finally:
            await asyncio.to_thread(path.unlink, True)

    async def _run(self, args: list[str]) -> tuple[bytes, bytes, int]:
        try:
            proc = await asyncio.create_subprocess_exec(
                self._exe,
                *args,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            raise ProvenanceInspectionError("c2patool could not be started") from exc
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), self._timeout)
        except TimeoutError as exc:
            proc.kill()
            await proc.wait()
            raise ProvenanceInspectionError("c2patool timed out") from exc
        if len(stdout) > _MAX_OUTPUT:
            raise ProvenanceInspectionError("c2patool output exceeded the size limit")
        return stdout, stderr, proc.returncode or 0


def _parse_json(text: str, what: str) -> dict[str, Any]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProvenanceInspectionError(f"c2patool returned invalid {what} JSON") from exc
    if not isinstance(payload, dict):
        raise ProvenanceInspectionError(f"c2patool returned unexpected {what} output")
    return payload
