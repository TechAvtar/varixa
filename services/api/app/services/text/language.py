"""Language detection (statistical, probabilistic). Reported with confidence, never as fact."""

from dataclasses import dataclass

from langdetect import DetectorFactory, LangDetectException, detect_langs

DetectorFactory.seed = 0  # deterministic results for identical input
MIN_CHARS = 20
ENGINE = "langdetect"


@dataclass(frozen=True)
class LanguageGuess:
    language: str | None  # ISO 639-1 code, e.g. "en"
    confidence: float | None  # 0-1 from the detector; not calibrated
    candidates: list[dict[str, float]]
    engine: str = ENGINE
    reason: str | None = None  # why no guess was made


def detect_language(text: str) -> LanguageGuess:
    sample = text.strip()
    if len(sample) < MIN_CHARS:
        return LanguageGuess(None, None, [], reason=f"fewer than {MIN_CHARS} characters")
    try:
        langs = detect_langs(sample[:20_000])
    except LangDetectException:
        return LanguageGuess(None, None, [], reason="no recognisable language features")
    candidates = [{"lang": lang.lang, "prob": round(float(lang.prob), 4)} for lang in langs[:5]]
    if not candidates:
        return LanguageGuess(None, None, [], reason="detector returned no candidates")
    best = candidates[0]
    return LanguageGuess(str(best["lang"]), float(best["prob"]), candidates)
