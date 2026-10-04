"""Local open-source AI-generation detectors (image and text) run on this machine.

Two community classifiers are loaded *offline* from ``VERIXA_AI_DETECTOR_MODEL_DIR`` (fetched
once with ``scripts/fetch_detector_models.py``); the service itself never downloads a model and
sends neither the content nor anything derived from it anywhere.

These are weak signals. They are trained on a limited set of generators, are not calibrated
and degrade on newer generators, edited, compressed or short content, so the engine caps what
they can say at POSSIBLE and every result carries those limitations.

``torch`` and ``transformers`` are optional (the ``ml`` extra) and imported lazily; inference is
blocking CPU work and therefore runs in a worker thread, one request at a time.
"""

import asyncio
import importlib
import io
import json
import threading
import time
from collections.abc import Awaitable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.providers.ai.base import (
    GENERIC_LIMITATIONS,
    AIDetectorError,
    AIDetectorUnavailableError,
    DetectionResult,
    Modality,
    label_for_score,
)

META_FILE = "verixa-model.json"
FETCH_HINT = "python scripts/fetch_detector_models.py"
EXTRA_HINT = 'pip install -e ".[ml]"'

IMAGE_LIMITATIONS = [
    "Local open-source image classifier: it was trained on a limited set of image generators "
    "and is not calibrated. It misses newer generators and can flag real photographs, "
    "screenshots and heavily compressed or edited images.",
]
TEXT_LIMITATIONS = [
    "Local open-source text classifier trained on older machine-written text (GPT-2 era). It "
    "is unreliable on modern AI writing, translated, edited or short text, and is known to "
    "flag human text, especially by non-native English writers.",
]


def model_slug(repo_id: str) -> str:
    """Directory name for a model repo id (``org/name`` -> ``org--name``)."""
    return repo_id.replace("/", "--")


@dataclass(frozen=True)
class Scored:
    """A classifier's answer: probability of every label, and how much input it covered."""

    probabilities: dict[str, float]
    units: int = 1  # images: 1; text: windows scored
    tokens: int = 0


class ClassifierRuntime:
    """What the detector needs from an inference engine (a fake in tests, transformers live)."""

    def image_model_info(self) -> tuple[str, str]:
        raise NotImplementedError

    def text_model_info(self) -> tuple[str, str]:
        raise NotImplementedError

    def prepare(self, modality: Modality) -> None:
        """Load what ``modality`` needs (slow, once). A no-op for engines with nothing to load."""

    def classify_image(self, data: bytes) -> Scored:
        raise NotImplementedError

    def classify_text(self, text: str) -> Scored | None:
        """None when the text is too short to score."""
        raise NotImplementedError


def _read_meta(model_dir: Path) -> dict[str, Any]:
    try:
        data = json.loads((model_dir / META_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def model_revision(model_dir: Path) -> str:
    """Pinned revision recorded by the fetch script (``unknown`` when absent)."""
    revision = _read_meta(model_dir).get("revision")
    return str(revision)[:12] if revision else "unknown"


class TransformersRuntime(ClassifierRuntime):
    """Lazy, thread-safe ``transformers`` classifiers loaded with ``local_files_only``."""

    def __init__(
        self,
        *,
        model_dir: Path,
        image_model: str,
        image_ai_label: str,
        text_model: str,
        text_ai_label: str,
        text_min_tokens: int,
        text_max_chunks: int,
    ) -> None:
        self._root = model_dir
        self._image_model = image_model
        self._image_label = image_ai_label
        self._text_model = text_model
        self._text_label = text_ai_label
        self._min_tokens = text_min_tokens
        self._max_chunks = text_max_chunks
        self._lock = threading.Lock()
        self._image: tuple[Any, Any] | None = None
        self._text: tuple[Any, Any] | None = None
        self._torch: Any = None
        self._transformers: Any = None

    # -- model identity (cheap; used for the cache key before anything is loaded) -------------

    def image_model_info(self) -> tuple[str, str]:
        return self._image_model, model_revision(self._root / model_slug(self._image_model))

    def text_model_info(self) -> tuple[str, str]:
        return self._text_model, model_revision(self._root / model_slug(self._text_model))

    # -- loading ---------------------------------------------------------------------------------

    def _libraries(self) -> Any:
        """The ``transformers`` module (``self._torch`` is set as a side effect)."""
        if self._torch is None or self._transformers is None:
            try:
                self._torch = importlib.import_module("torch")
                self._transformers = importlib.import_module("transformers")
            except ImportError as exc:
                raise AIDetectorUnavailableError(
                    f"the local detector needs the optional ML libraries ({EXTRA_HINT})"
                ) from exc
        return self._transformers

    def _model_path(self, repo_id: str) -> Path:
        path = self._root / model_slug(repo_id)
        if not (path / "config.json").is_file():
            raise AIDetectorUnavailableError(
                f"model '{repo_id}' is not in {self._root}; fetch it once with {FETCH_HINT}"
            )
        return path

    def _check_label(self, model: Any, label: str, repo_id: str) -> None:
        labels = {str(v) for v in model.config.id2label.values()}
        if label not in labels:
            raise AIDetectorUnavailableError(
                f"label '{label}' is not one of {sorted(labels)} for model '{repo_id}'; "
                "set VERIXA_AI_DETECTOR_*_AI_LABEL"
            )

    def _load_image(self) -> tuple[Any, Any]:
        if self._image is None:
            tf = self._libraries()
            path = self._model_path(self._image_model)
            processor = tf.AutoImageProcessor.from_pretrained(path, local_files_only=True)
            model = tf.AutoModelForImageClassification.from_pretrained(path, local_files_only=True)
            model.eval()
            self._check_label(model, self._image_label, self._image_model)
            self._image = (processor, model)
        return self._image

    def _load_text(self) -> tuple[Any, Any]:
        if self._text is None:
            tf = self._libraries()
            path = self._model_path(self._text_model)
            tokenizer = tf.AutoTokenizer.from_pretrained(path, local_files_only=True)
            model = tf.AutoModelForSequenceClassification.from_pretrained(
                path, local_files_only=True
            )
            model.eval()
            self._check_label(model, self._text_label, self._text_model)
            self._text = (tokenizer, model)
        return self._text

    def prepare(self, modality: Modality) -> None:
        with self._lock:
            if modality == "image":
                self._load_image()
            else:
                self._load_text()

    # -- inference -------------------------------------------------------------------------------

    def _probabilities(self, model: Any, logits: Any) -> list[dict[str, float]]:
        probs = self._torch.softmax(logits, dim=-1).tolist()
        names = [str(model.config.id2label[i]) for i in range(len(probs[0]))]
        return [dict(zip(names, (float(x) for x in row), strict=True)) for row in probs]

    def classify_image(self, data: bytes) -> Scored:
        with self._lock:
            processor, model = self._load_image()
            from PIL import Image  # local import: Pillow is only needed once a model runs

            try:
                with Image.open(io.BytesIO(data)) as img:
                    rgb = img.convert("RGB")
            except Exception as exc:  # decoding already succeeded upstream; be defensive
                raise AIDetectorError("the image could not be decoded for the detector") from exc
            inputs = processor(images=rgb, return_tensors="pt")
            with self._torch.inference_mode():
                logits = model(**inputs).logits
            return Scored(probabilities=self._probabilities(model, logits)[0])

    def classify_text(self, text: str) -> Scored | None:
        with self._lock:
            tokenizer, model = self._load_text()
            window = min(int(getattr(tokenizer, "model_max_length", 512) or 512), 512)
            ids: list[int] = tokenizer(text, add_special_tokens=False, truncation=False)[
                "input_ids"
            ]
            if len(ids) < self._min_tokens:
                return None
            body = window - 2  # room for the start and end tokens
            chunks = [ids[i : i + body] for i in range(0, len(ids), body)]
            # A short trailing window carries little signal; keep it only when it is the only one.
            if len(chunks) > 1 and len(chunks[-1]) < self._min_tokens:
                chunks.pop()
            chunks = chunks[: self._max_chunks]
            weights = [len(c) for c in chunks]
            total: dict[str, float] = {}
            with self._torch.inference_mode():
                for chunk, weight in zip(chunks, weights, strict=True):
                    framed = [
                        i
                        for i in (tokenizer.cls_token_id, *chunk, tokenizer.sep_token_id)
                        if i is not None
                    ]
                    input_ids = self._torch.tensor([framed])
                    logits = model(
                        input_ids=input_ids, attention_mask=self._torch.ones_like(input_ids)
                    ).logits
                    for name, p in self._probabilities(model, logits)[0].items():
                        total[name] = total.get(name, 0.0) + p * weight
            norm = float(sum(weights))
            return Scored(
                probabilities={k: v / norm for k, v in total.items()},
                units=len(chunks),
                tokens=int(sum(weights)),
            )


class LocalAIDetector:
    name = "local"
    modalities = frozenset({"image", "text"})

    def __init__(
        self,
        runtime: ClassifierRuntime,
        *,
        image_ai_label: str,
        text_ai_label: str,
        high: float,
        medium: float,
        timeout_seconds: float,
        load_timeout_seconds: float = 300.0,
    ) -> None:
        self._runtime = runtime
        self._load_timeout = load_timeout_seconds
        self._labels = {"image": image_ai_label, "text": text_ai_label}
        self._high = high
        self._medium = medium
        self._timeout = timeout_seconds

    def model_hint(self) -> str:
        """Identity of both models, part of the cache key (changes when a model is re-fetched)."""
        image = "@".join(self._runtime.image_model_info())
        text = "@".join(self._runtime.text_model_info())
        return f"image={image};text={text}"

    async def detect(
        self, content: bytes | str, *, modality: Modality, metadata: dict[str, Any]
    ) -> DetectionResult:
        started = time.perf_counter()
        scored: Scored | None
        work: Awaitable[Scored | None]
        try:
            # Loading a model is slow and happens once; it must not eat the scoring budget.
            await asyncio.wait_for(
                asyncio.to_thread(self._runtime.prepare, modality), timeout=self._load_timeout
            )
            started = time.perf_counter()
            if modality == "image":
                if not isinstance(content, bytes):
                    raise AIDetectorUnavailableError("image detection needs the image bytes")
                work = asyncio.to_thread(self._runtime.classify_image, content)
                model, version = self._runtime.image_model_info()
                limitations = IMAGE_LIMITATIONS
            else:
                text = content if isinstance(content, str) else content.decode("utf-8", "replace")
                work = asyncio.to_thread(self._runtime.classify_text, text)
                model, version = self._runtime.text_model_info()
                limitations = TEXT_LIMITATIONS
            scored = await asyncio.wait_for(work, timeout=self._timeout)
        except AIDetectorError:
            raise
        except TimeoutError as exc:
            raise AIDetectorError("the local detector timed out") from exc
        except Exception as exc:
            # Never echo model/tensor internals; the class name is enough to diagnose.
            raise AIDetectorError(f"the local detector failed ({exc.__class__.__name__})") from exc

        latency = int((time.perf_counter() - started) * 1000)
        if scored is None:
            return DetectionResult(
                provider=self.name,
                model=model,
                model_version=version,
                modality=modality,
                score=None,
                label="unavailable",
                calibrated=False,
                raw={"reason": "too_short"},
                latency_ms=latency,
                estimated_cost=0.0,
                limitations=[
                    "The text is too short for the local classifier to give a usable score.",
                    *limitations,
                    *GENERIC_LIMITATIONS,
                ],
            )
        ai_label = self._labels[modality]
        if ai_label not in scored.probabilities:
            raise AIDetectorUnavailableError(
                f"label '{ai_label}' missing from the model output {sorted(scored.probabilities)}"
            )
        score = round(scored.probabilities[ai_label], 4)
        return DetectionResult(
            provider=self.name,
            model=model,
            model_version=version,
            modality=modality,
            score=score,
            label=label_for_score(score, high=self._high, medium=self._medium),
            calibrated=False,
            raw={
                "probabilities": {k: round(v, 4) for k, v in scored.probabilities.items()},
                "ai_label": ai_label,
                "windows": scored.units,
                "tokens": scored.tokens,
            },
            latency_ms=latency,
            estimated_cost=0.0,
            limitations=[*limitations, *GENERIC_LIMITATIONS],
        )
