"""Lineage read from metadata: generator markers, declared digital source type, XMP edit history.

Everything here is *declared by software*, never verified: a generator writes its prompt into
a PNG text chunk, an editor writes ``xmpMM:History``, a producer sets the IPTC digital source
type. Tags can be stripped or forged, so the evidence engine caps these at STRONG at best.
Works on both extractor shapes: ExifTool's flat ``Group:Tag`` keys with ``-struct`` lists, and
Pillow's nested ``xmpmeta`` dictionary.
"""

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from app.providers.metadata.base import RawMetadata

_EXCERPT = 240

# Software / creator strings that name a generator outright.
_GENERATOR_NAMES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern, re.I), label)
    for pattern, label in (
        (r"stable[\s_-]?diffusion|sd[\s_-]?webui|automatic1111|a1111|forge", "Stable Diffusion"),
        (r"comfy[\s_-]?ui", "ComfyUI"),
        (r"novel[\s_-]?ai", "NovelAI"),
        (r"midjourney", "Midjourney"),
        (r"dall[\s·._-]?e", "DALL-E"),
        (r"adobe firefly|firefly", "Adobe Firefly"),
        (r"fooocus", "Fooocus"),
        (r"invoke[\s_-]?ai", "InvokeAI"),
        (r"leonardo\.?ai|leonardo ai", "Leonardo AI"),
        (r"ideogram", "Ideogram"),
        (r"\bflux(\.1|[\s_-]?(dev|schnell|pro))?\b", "FLUX"),
        (r"imagen|gemini image|nano banana", "Google Imagen"),
        (r"bing image creator|designer\.microsoft", "Bing Image Creator"),
        (r"playground ?ai|playgroundai", "Playground AI"),
        (r"\bnijijourney\b", "Niji Journey"),
        (r"krea\.ai|krea ai", "Krea"),
        (r"\bai[\s_-]?generated\b", "unspecified AI generator"),
    )
)

# PNG text keys that generators use for prompts / workflows (lower-cased for matching).
_PNG_GENERATOR_KEYS: dict[str, str] = {
    "parameters": "Stable Diffusion WebUI",  # AUTOMATIC1111 / Forge / SD.Next
    "prompt": "ComfyUI",
    "workflow": "ComfyUI",
    "sd-metadata": "InvokeAI",
    "invokeai_metadata": "InvokeAI",
    "invokeai_graph": "InvokeAI",
    "dream": "InvokeAI",
    "fooocus_scheme": "Fooocus",
    "generation_data": "unspecified AI generator",
}

# Tokens inside a generic PNG Comment / Description that betray a generation payload.
_PAYLOAD_TOKENS = re.compile(
    r'"(steps|sampler|cfg_scale|scale|seed|uc|prompt|denoising_strength|model_hash)"\s*:'
    r"|\bSteps:\s*\d+|\bSampler:|\bCFG scale:|\bSeed:\s*\d+|\bModel hash:",
    re.I,
)

_SOURCE_TYPE_PREFIX = "http://cv.iptc.org/newscodes/digitalsourcetype/"
# IPTC digital source types that declare algorithmic (AI) origin.
ALGORITHMIC_SOURCE_TYPES = frozenset(
    {"trainedAlgorithmicMedia", "algorithmicMedia", "compositeWithTrainedAlgorithmicMedia"}
)


@dataclass(frozen=True)
class GeneratorSignal:
    generator: str
    tag: str  # where it was found, e.g. "PNG:Parameters"
    excerpt: str  # bounded text of the marker; may contain the generation prompt


@dataclass(frozen=True)
class EditEvent:
    action: str
    software: str | None
    when: str | None  # as recorded
    changed: str | None
    instance_id: str | None


@dataclass
class Lineage:
    generator: str | None = None
    generator_signals: list[GeneratorSignal] = field(default_factory=list)
    digital_source_type: str | None = None  # last path segment, e.g. "trainedAlgorithmicMedia"
    creator_tool: str | None = None
    document_id: str | None = None
    instance_id: str | None = None
    original_document_id: str | None = None
    derived_from_document_id: str | None = None
    edit_history: list[EditEvent] = field(default_factory=list)

    @property
    def declares_algorithmic_source(self) -> bool:
        return self.digital_source_type in ALGORITHMIC_SOURCE_TYPES

    def to_json(self) -> dict[str, Any]:
        return {
            "generator": self.generator,
            "generator_signals": [asdict(s) for s in self.generator_signals],
            "digital_source_type": self.digital_source_type,
            "creator_tool": self.creator_tool,
            "document_id": self.document_id,
            "instance_id": self.instance_id,
            "original_document_id": self.original_document_id,
            "derived_from_document_id": self.derived_from_document_id,
            "edit_history": [asdict(e) for e in self.edit_history],
        }


# -- XMP access that tolerates both extractor shapes -----------------------------------------------
def xmp_properties(raw: RawMetadata) -> dict[str, Any]:
    """Flat ``{property: value}`` from the XMP group, case as written by the extractor."""
    group = raw.group("XMP")
    nested = group.get("xmpmeta")
    while isinstance(nested, dict) and isinstance(nested.get("xmpmeta"), dict):
        nested = nested["xmpmeta"]  # the extractor wraps Pillow's own {"xmpmeta": ...} once more
    if isinstance(nested, dict):  # Pillow: {"xmpmeta": {"RDF": {"Description": {...}|[...]}}}
        rdf = nested.get("RDF") if isinstance(nested.get("RDF"), dict) else {}
        desc = rdf.get("Description") if isinstance(rdf, dict) else None
        merged: dict[str, Any] = {}
        for d in desc if isinstance(desc, list) else [desc]:
            if isinstance(d, dict):
                merged.update(d)
        return merged
    return {k.split(":")[-1]: v for k, v in group.items()}  # ExifTool: "XMP-xmpMM:History"


def _prop(props: dict[str, Any], *names: str) -> Any:
    lowered = {k.lower(): v for k, v in props.items()}
    for name in names:
        if name.lower() in lowered:
            return lowered[name.lower()]
    return None


def _text(value: Any, limit: int = 200) -> str | None:
    if value is None or isinstance(value, dict | list):
        return None
    text = str(value).strip()
    return text[:limit] or None


def _history_items(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [v for v in value if isinstance(v, dict)]
    if isinstance(value, dict):
        seq = value.get("Seq") or value.get("seq")
        if isinstance(seq, dict):
            li = seq.get("li")
            return _history_items(li if isinstance(li, list) else [li])
        return [value]
    return []


def edit_history(raw: RawMetadata) -> list[EditEvent]:
    props = xmp_properties(raw)
    events: list[EditEvent] = []
    for item in _history_items(_prop(props, "History"))[:50]:
        low = {k.lower(): v for k, v in item.items()}
        action = _text(low.get("action"), 40)
        if not action:
            continue
        events.append(
            EditEvent(
                action=action,
                software=_text(low.get("softwareagent")),
                when=_text(low.get("when"), 64),
                changed=_text(low.get("changed"), 80),
                instance_id=_text(low.get("instanceid"), 120),
            )
        )
    return events


def digital_source_type(raw: RawMetadata) -> str | None:
    value = _text(_prop(xmp_properties(raw), "DigitalSourceType")) or _text(
        raw.get("IPTC", "DigitalSourceType")
    )
    if not value:
        return None
    return value.removeprefix(_SOURCE_TYPE_PREFIX).rstrip("/").split("/")[-1][:80]


# -- generator markers -----------------------------------------------------------------------------
def _name_match(text: str | None) -> str | None:
    if not text:
        return None
    for pattern, label in _GENERATOR_NAMES:
        if pattern.search(text):
            return label
    return None


def generator_signals(raw: RawMetadata) -> list[GeneratorSignal]:
    signals: list[GeneratorSignal] = []
    seen: set[str] = set()

    def add(generator: str, tag: str, value: Any) -> None:
        key = f"{tag}"
        if key in seen:
            return
        seen.add(key)
        excerpt = re.sub(r"\s+", " ", str(value)).strip()[:_EXCERPT]
        signals.append(GeneratorSignal(generator=generator, tag=tag, excerpt=excerpt))

    # 1. PNG text chunks written by generators.
    for key, value in raw.group("PNG").items():
        name = key.split(":")[-1]
        low = name.lower()
        if value in (None, ""):
            continue
        if low in _PNG_GENERATOR_KEYS:
            add(_name_match(str(value)) or _PNG_GENERATOR_KEYS[low], f"PNG:{name}", value)
        elif low in {"comment", "description", "software", "source", "title"}:
            named = _name_match(str(value))
            if named:
                add(named, f"PNG:{name}", value)
            elif _PAYLOAD_TOKENS.search(str(value)):
                add("unspecified AI generator", f"PNG:{name}", value)

    # 2. Software / creator / description strings in EXIF and XMP.
    props = xmp_properties(raw)
    for tag, value in (
        ("EXIF:Software", raw.get("EXIF", "Software")),
        ("EXIF:ImageDescription", raw.get("EXIF", "ImageDescription")),
        ("EXIF:UserComment", raw.get("EXIF", "UserComment")),
        ("XMP:CreatorTool", _prop(props, "CreatorTool")),
        ("XMP:Description", _prop(props, "Description", "description")),
        ("XMP:Credit", _prop(props, "Credit")),
    ):
        text = _text(value, 4000) if not isinstance(value, dict) else None
        if isinstance(value, dict):  # XMP lang-alt: {"x-default": "..."} or Pillow {"Alt": ...}
            text = _text(next(iter(value.values()), None), 4000) if value else None
        named = _name_match(text)
        if named:
            add(named, tag, text)
    return signals


def extract_lineage(raw: RawMetadata) -> Lineage:
    props = xmp_properties(raw)
    signals = generator_signals(raw)
    return Lineage(
        generator=signals[0].generator if signals else None,
        generator_signals=signals,
        digital_source_type=digital_source_type(raw),
        creator_tool=_text(_prop(props, "CreatorTool")),
        document_id=_text(_prop(props, "DocumentID"), 120),
        instance_id=_text(_prop(props, "InstanceID"), 120),
        original_document_id=_text(_prop(props, "OriginalDocumentID"), 120),
        derived_from_document_id=_derived_from(props),
        edit_history=edit_history(raw),
    )


def _derived_from(props: dict[str, Any]) -> str | None:
    value = _prop(props, "DerivedFrom")
    if isinstance(value, dict):
        low = {k.lower(): v for k, v in value.items()}
        return _text(low.get("documentid") or low.get("instanceid"), 120)
    return _text(_prop(props, "DerivedFromDocumentID"), 120)
