"""c2patool adapter (Content Authenticity Initiative reference CLI).

c2patool only reads files, so the verified bytes are written to a private temp
file with a random name and the *validated* extension, then removed. Runs per
inspection: ``--info`` (one-line facts), the summary (manifest store) and ``-d``
(detailed, includes validation_status / validation_results).

The binary's capabilities (version and the flags its ``--help`` lists) are probed
once per process and cached, so features are switched on by *flag presence*, never
by comparing version numbers; a renamed flag simply disables a feature.
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.providers.provenance.base import ProvenanceInspectionError, RawProvenance

log = logging.getLogger("verixa.providers.c2patool")

_MAX_OUTPUT = 16 * 1024 * 1024
_MAX_INFO = 4 * 1024
_MAX_TREE = 64 * 1024
_NO_CLAIM_MARKERS = ("No claim found", "no claim found", "no manifest")
# 0.28 with fetching disabled refuses a remote reference; without it, it would try the network.
_REMOTE_MARKERS = (
    "must fetch remote manifests from url",
    "could not fetch the remote manifest",
    "Unable to fetch cloud manifest",
)
_URL_RE = re.compile(r"https?://[^\s'\"]+")
# Only extensions c2patool understands for the formats Verixa accepts; anything else -> "bin".
_SAFE_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "tif", "tiff"}
_FLAG_RE = re.compile(r"(?m)^\s*(?:-\w,\s*)?(--[a-z][a-z0-9_-]*)")
_SUBCOMMAND_RE = re.compile(r"(?m)^\s{2,}([a-z][a-z0-9_-]*)\s{2,}\S")

# Newest pinned release first (the README's Windows install folder), then older layouts.
_WINDOWS_CANDIDATES = (
    Path.home() / "AppData/Local/Programs/c2patool-0.28.0/c2patool.exe",
    Path.home() / "AppData/Local/Programs/c2patool/c2patool/c2patool.exe",
    Path.home() / "AppData/Local/Programs/c2patool/c2patool.exe",
)

# c2pa-rs settings shipped with the adapter: no remote-manifest fetch, no OCSP.
SETTINGS_FILE = Path(__file__).with_name("c2pa_settings.toml")
# Official C2PA trust list bundled with the adapter (refreshed by scripts/refresh_trust_list.py).
BUNDLED_TRUST_DIR = Path(__file__).with_name("trust")
BUNDLED_TRUST_PEM = BUNDLED_TRUST_DIR / "C2PA-TRUST-LIST.pem"
BUNDLED_TRUST_META = BUNDLED_TRUST_DIR / "C2PA-TRUST-LIST.meta.json"


@dataclass(frozen=True)
class TrustFiles:
    """Local trust material for the engine's trust run. Files only, never URLs."""

    mode: str  # bundled | custom
    anchors: Path | None = None
    allowed_list: Path | None = None
    trust_config: Path | None = None
    list_version: str | None = None

    @property
    def cwd(self) -> Path:
        first = self.anchors or self.allowed_list or self.trust_config
        assert first is not None
        return first.parent

    def args(self) -> list[str]:
        """`trust` subcommand options with paths *relative to cwd*: the engine parses these
        options as URL-or-relative-path, so an absolute Windows path would be read as a URL."""
        out: list[str] = []
        for flag, path in (
            ("--trust_anchors", self.anchors),
            ("--allowed_list", self.allowed_list),
            ("--trust_config", self.trust_config),
        ):
            if path is None:
                continue
            try:
                rel = os.path.relpath(path, self.cwd)
            except ValueError as exc:  # different drives on Windows
                raise ProvenanceInspectionError(
                    "trust files must live on the same drive/volume"
                ) from exc
            out += [flag, rel]
        return out


def file_version(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def bundled_trust_files() -> TrustFiles | None:
    if not BUNDLED_TRUST_PEM.is_file():
        return None
    version: str | None = None
    if BUNDLED_TRUST_META.is_file():
        try:
            meta = json.loads(BUNDLED_TRUST_META.read_text("utf-8"))
            digest = meta.get("sha256")
            version = str(digest)[:12] if isinstance(digest, str) else None
        except (OSError, ValueError):
            version = None
    return TrustFiles(
        mode="bundled",
        anchors=BUNDLED_TRUST_PEM,
        list_version=version or file_version(BUNDLED_TRUST_PEM),
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


@dataclass(frozen=True)
class C2paToolCapabilities:
    """What the installed binary offers, read from ``--version`` and ``--help``."""

    version: str
    flags: frozenset[str]
    subcommands: frozenset[str]

    @property
    def version_tuple(self) -> tuple[int, ...]:
        return tuple(int(p) for p in re.findall(r"\d+", self.version)[:3])

    def has_flag(self, flag: str) -> bool:
        return flag in self.flags

    @property
    def has_trust_subcommand(self) -> bool:
        return "trust" in self.subcommands

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        data["flags"] = sorted(self.flags)
        data["subcommands"] = sorted(self.subcommands)
        return data


def parse_help(version_text: str, help_text: str) -> C2paToolCapabilities:
    """Pure parser for the probe output (unit-tested without the binary)."""
    version = version_text.strip().removeprefix("c2patool").strip() or "unknown"
    flags = frozenset(m.group(1) for m in _FLAG_RE.finditer(help_text))
    subcommands = frozenset(
        m.group(1)
        for m in _SUBCOMMAND_RE.finditer(help_text)
        if m.group(1) not in {"help", "options", "arguments", "usage"}
    )
    return C2paToolCapabilities(version=version, flags=flags, subcommands=subcommands)


# One probe per binary per process; keyed by path and mtime so an upgrade is noticed.
_CAPABILITY_CACHE: dict[tuple[str, int], C2paToolCapabilities] = {}


class C2paToolInspector:
    name = "c2patool"

    def __init__(
        self,
        executable: str,
        *,
        temp_dir: Path,
        timeout_seconds: float = 30.0,
        settings_file: Path | None = SETTINGS_FILE,
        trust: TrustFiles | None = None,
    ) -> None:
        self._exe = executable
        self._temp_dir = temp_dir
        self._timeout = timeout_seconds
        # None = let the engine use its defaults (which include fetching remote manifests).
        self._settings_file = settings_file
        # None = trust not evaluated (reported as such); otherwise a second, separate run.
        self._trust = trust

    @property
    def trust(self) -> TrustFiles | None:
        return self._trust

    def asset_args(self, path: Path, caps: C2paToolCapabilities) -> list[str]:
        """Arguments every asset run starts with. Only a local path and, when the engine
        supports it, our settings file: never a URL, never anything from the asset."""
        args = [str(path)]
        if self._settings_file is not None and caps.has_flag("--settings"):
            args += ["--settings", str(self._settings_file)]
        return args

    async def version(self) -> str:
        return (await self.capabilities()).version

    async def capabilities(self) -> C2paToolCapabilities:
        try:
            mtime = Path(self._exe).stat().st_mtime_ns
        except OSError:
            mtime = 0
        key = (self._exe, mtime)
        cached = _CAPABILITY_CACHE.get(key)
        if cached is not None:
            return cached
        version_out, _, _ = await self._run(["--version"])
        help_out, help_err, _ = await self._run(["--help"])
        caps = parse_help(
            version_out.decode("ascii", "replace"),
            (help_out + help_err).decode("utf-8", "replace"),
        )
        _CAPABILITY_CACHE[key] = caps
        log.info(
            "c2patool probed",
            extra={"version": caps.version, "flags": len(caps.flags)},
        )
        return caps

    async def inspect(self, data: bytes, *, extension: str) -> RawProvenance:
        ext = extension.lower().lstrip(".")
        if ext not in _SAFE_EXTENSIONS:
            ext = "bin"
        self._temp_dir.mkdir(parents=True, exist_ok=True)
        # Absolute: the trust run changes the working directory to the trust files' folder.
        path = (self._temp_dir / f"c2pa-{uuid.uuid4().hex}.{ext}").resolve()
        try:
            await asyncio.to_thread(path.write_bytes, data)
            caps = await self.capabilities()
            version = caps.version
            base = self.asset_args(path, caps)
            summary_out, summary_err, rc = await self._run(base)
            summary_text = summary_out.decode("utf-8", "replace")
            err_text = summary_err.decode("utf-8", "replace")
            if any(marker in summary_text + err_text for marker in _NO_CLAIM_MARKERS):
                return RawProvenance(
                    engine=self.name,
                    engine_version=version,
                    present=False,
                    capabilities=caps.to_json(),
                )
            remote_host = remote_host_from_error(summary_text + err_text)
            if remote_host is not None:
                return RawProvenance(
                    engine=self.name,
                    engine_version=version,
                    present=False,
                    warnings=["remote manifest reference not fetched"],
                    capabilities=caps.to_json(),
                    remote_manifest_host=remote_host,
                )
            if rc != 0 and not summary_text.lstrip().startswith("{"):
                first = next((ln.strip() for ln in err_text.splitlines() if ln.strip()), "")
                raise ProvenanceInspectionError(
                    f"c2patool could not read the file: {first[:200] or 'unknown error'}"
                )
            summary = _parse_json(summary_text, "summary")

            detailed_out, detailed_err, _ = await self._run([*base, "-d"])
            detailed = _parse_json(detailed_out.decode("utf-8", "replace"), "detailed")
            # 0.9.x reports validation in the detailed output only; 0.28+ reports the
            # structured results (and the flat problem list) in both. Prefer detailed.
            status = detailed.get("validation_status") or summary.get("validation_status") or []
            results = detailed.get("validation_results") or summary.get("validation_results")
            state = detailed.get("validation_state") or summary.get("validation_state")

            info: str | None = None
            if caps.has_flag("--info"):
                info_out, _, _ = await self._run([*base, "--info"])
                info = info_out.decode("utf-8", "replace").strip()[:_MAX_INFO] or None
            tree: str | None = None
            if caps.has_flag("--tree"):
                tree_out, _, _ = await self._run([*base, "--tree"])
                tree = tree_out.decode("utf-8", "replace").strip()[:_MAX_TREE] or None

            warnings = [
                line.strip()
                for line in (summary_err + detailed_err).decode("utf-8", "replace").splitlines()
                if line.strip()
            ]

            trust_evaluated = False
            trust_state: str | None = None
            trust_status: list[dict[str, Any]] = []
            trust_results: dict[str, Any] | None = None
            if self._trust is not None and caps.has_trust_subcommand:
                trust_out, trust_err, trust_rc = await self._run(
                    [*base, "-d", "trust", *self._trust.args()], cwd=self._trust.cwd
                )
                trust_text = trust_out.decode("utf-8", "replace")
                if trust_rc == 0 and trust_text.lstrip().startswith("{"):
                    trust_json = _parse_json(trust_text, "trust")
                    trust_evaluated = True
                    trust_state = (
                        str(trust_json["validation_state"])
                        if isinstance(trust_json.get("validation_state"), str)
                        else None
                    )
                    raw_status = trust_json.get("validation_status") or []
                    trust_status = [s for s in raw_status if isinstance(s, dict)]
                    results = trust_json.get("validation_results")
                    trust_results = results if isinstance(results, dict) else None
                else:
                    first = next(
                        (
                            ln.strip()
                            for ln in trust_err.decode("utf-8", "replace").splitlines()
                            if ln.strip()
                        ),
                        "",
                    )
                    warnings.append(f"trust run failed: {first[:200] or 'no output'}")
            return RawProvenance(
                engine=self.name,
                engine_version=version,
                present=True,
                summary=summary,
                detailed=detailed,
                validation_status=[s for s in status if isinstance(s, dict)],
                warnings=warnings[:50],
                validation_results=results if isinstance(results, dict) else None,
                validation_state=str(state) if isinstance(state, str) else None,
                info=info,
                capabilities=caps.to_json(),
                tree=tree,
                trust_evaluated=trust_evaluated,
                trust_mode=self._trust.mode if self._trust is not None else None,
                trust_list_version=self._trust.list_version if self._trust is not None else None,
                trust_state=trust_state,
                trust_status=trust_status,
                trust_results=trust_results,
            )
        finally:
            await asyncio.to_thread(path.unlink, True)

    async def _run(self, args: list[str], cwd: Path | None = None) -> tuple[bytes, bytes, int]:
        """Run once; retry a single time only when the process could not start or was
        killed by a signal (transient host conditions). Timeouts and ordinary non-zero
        exits are never retried: the input is the same and the answer would be too."""
        last_error: ProvenanceInspectionError | None = None
        for attempt in range(2):
            try:
                return await self._run_once(args, cwd)
            except _TransientError as exc:
                last_error = ProvenanceInspectionError(str(exc))
                if attempt == 0:
                    log.warning("c2patool transient failure, retrying", extra={"reason": str(exc)})
                    continue
        assert last_error is not None
        raise last_error

    async def _run_once(self, args: list[str], cwd: Path | None = None) -> tuple[bytes, bytes, int]:
        try:
            proc = await asyncio.create_subprocess_exec(
                self._exe,
                *args,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(cwd) if cwd is not None else None,
            )
        except OSError as exc:
            raise _TransientError("c2patool could not be started") from exc
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), self._timeout)
        except TimeoutError as exc:
            proc.kill()
            await proc.wait()
            raise ProvenanceInspectionError("c2patool timed out") from exc
        if len(stdout) > _MAX_OUTPUT:
            raise ProvenanceInspectionError("c2patool output exceeded the size limit")
        rc = proc.returncode or 0
        if rc < 0:  # killed by a signal (POSIX); Windows never reports negative codes
            raise _TransientError(f"c2patool was killed by signal {-rc}")
        return stdout, stderr, rc


def remote_host_from_error(text: str) -> str | None:
    """Host of the remote manifest the engine refused to fetch, or None when the output is
    not that refusal. Only the host is returned: the URL stays out of logs and rows."""
    if not any(marker in text for marker in _REMOTE_MARKERS):
        return None
    m = _URL_RE.search(text)
    if not m:
        return "unknown host"
    from urllib.parse import urlsplit

    return (urlsplit(m.group(0)).hostname or "unknown host")[:253]


class _TransientError(Exception):
    """Internal: a failure worth exactly one retry."""


def _parse_json(text: str, what: str) -> dict[str, Any]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProvenanceInspectionError(f"c2patool returned invalid {what} JSON") from exc
    if not isinstance(payload, dict):
        raise ProvenanceInspectionError(f"c2patool returned unexpected {what} output")
    return payload
