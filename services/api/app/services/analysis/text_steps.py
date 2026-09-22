"""Pipeline steps for text analyses. Deterministic and local; no providers yet."""

import hashlib

from app.models import TextAnalysis, TextFingerprints
from app.providers.storage.base import ObjectNotFoundError
from app.repositories.analysis import AnalysisRepository
from app.services.analysis.ai_step import AIDetectionStep
from app.services.analysis.pipeline import (
    PipelineContext,
    PipelineStep,
    StepFailedError,
    StepOutcome,
)
from app.services.analysis.search_step import SourceSearchStep
from app.services.text import (
    compute_statistics,
    compute_structure,
    compute_text_fingerprints,
    detect_language,
    normalize_text,
)


class LoadAndNormalizeTextStep:
    """Reads the stored original, normalises it, and creates the text_analysis row."""

    name = "normalize"
    critical = True

    async def run(self, ctx: PipelineContext) -> StepOutcome:
        if ctx.file is None:
            raise StepFailedError("NO_FILE", "The analysis has no stored text.")
        try:
            data, _ = await ctx.storage.get(ctx.file.object_key)
        except ObjectNotFoundError as exc:
            raise StepFailedError("FILE_MISSING", "The stored text could not be found.") from exc
        if hashlib.sha256(data).hexdigest() != ctx.file.sha256:
            raise StepFailedError("HASH_MISMATCH", "The stored text does not match its record.")
        try:
            original = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise StepFailedError("BAD_ENCODING", "The stored text is not valid UTF-8.") from exc

        result = normalize_text(original)
        row = TextAnalysis(
            analysis_id=ctx.analysis.id,
            normalized_text=result.normalized,
            normalized_sha256=hashlib.sha256(result.normalized.encode("utf-8")).hexdigest(),
            normalization_json=result.report.__dict__,
            character_count=len(result.normalized),
        )
        await AnalysisRepository(ctx.session).replace_text_analysis(row)
        ctx.artifacts["text"] = result
        ctx.artifacts["text_row"] = row
        return StepOutcome.ok(
            original_chars=len(original),
            normalized_chars=len(result.normalized),
            changed=result.report.changed,
            zero_width_removed=result.report.zero_width_removed,
            bidi_controls_removed=result.report.bidi_controls_removed,
            control_chars_removed=result.report.control_chars_removed,
            normalized_sha256=row.normalized_sha256,
        )


def _row(ctx: PipelineContext) -> TextAnalysis:
    row = ctx.artifacts.get("text_row")
    if row is None:
        raise StepFailedError("NO_NORMALIZED_TEXT", "Normalisation did not run.")
    return row  # type: ignore[no-any-return]


class DetectLanguageStep:
    name = "language"
    critical = False

    async def run(self, ctx: PipelineContext) -> StepOutcome:
        row = _row(ctx)
        guess = detect_language(row.normalized_text)
        row.language = guess.language
        row.language_confidence = guess.confidence
        row.language_json = {
            "language": guess.language,
            "confidence": guess.confidence,
            "candidates": guess.candidates,
            "engine": guess.engine,
            "reason": guess.reason,
        }
        await ctx.session.flush()
        if guess.language is None:
            return StepOutcome.skipped(guess.reason or "no language detected", engine=guess.engine)
        return StepOutcome.ok(
            language=guess.language, confidence=guess.confidence, engine=guess.engine
        )


class TextStatisticsStep:
    name = "statistics"
    critical = True

    async def run(self, ctx: PipelineContext) -> StepOutcome:
        row = _row(ctx)
        stats = compute_statistics(row.normalized_text)
        structure = compute_structure(row.normalized_text)
        row.word_count = stats.word_count
        row.character_count = stats.character_count
        row.sentence_count = stats.sentence_count
        row.paragraph_count = stats.paragraph_count
        row.statistics_json = stats.to_json()
        row.structure_json = structure.to_json()
        await ctx.session.flush()
        ctx.artifacts["text_statistics"] = stats
        return StepOutcome.ok(
            words=stats.word_count,
            sentences=stats.sentence_count,
            paragraphs=stats.paragraph_count,
            type_token_ratio=stats.type_token_ratio,
            repeated_sentences=stats.repeated_sentence_count,
        )


class TextFingerprintsStep:
    name = "fingerprints"
    critical = True

    async def run(self, ctx: PipelineContext) -> StepOutcome:
        row = _row(ctx)
        if ctx.file is None:
            raise StepFailedError("NO_FILE", "The analysis has no stored text.")
        original = ctx.artifacts["text"].original
        fp = compute_text_fingerprints(original, row.normalized_text)
        await AnalysisRepository(ctx.session).replace_text_fingerprints(
            TextFingerprints(
                analysis_id=ctx.analysis.id,
                sha256=fp.sha256,
                normalized_sha256=fp.normalized_sha256,
                canonical_sha256=fp.canonical_sha256,
                minhash_json=fp.minhash,
                shingle_count=fp.shingle_count,
                algorithm_version=fp.version,
            )
        )
        ctx.artifacts["text_fingerprints"] = fp
        return StepOutcome.ok(
            sha256=fp.sha256,
            normalized_sha256=fp.normalized_sha256,
            canonical_sha256=fp.canonical_sha256,
            shingle_count=fp.shingle_count,
            algorithm_version=fp.version,
        )


def text_pipeline_steps() -> list[PipelineStep]:
    """Ordered steps for a text analysis. Later tasks append AI, search, ..."""
    return [
        LoadAndNormalizeTextStep(),
        DetectLanguageStep(),
        TextStatisticsStep(),
        TextFingerprintsStep(),
        AIDetectionStep(),
        SourceSearchStep(),
    ]
