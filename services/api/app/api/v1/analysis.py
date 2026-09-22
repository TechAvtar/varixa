import uuid
from typing import Annotated

from fastapi import APIRouter, File, Form, Query, UploadFile, status

from app.api.deps import AnalysisSvc, AppSettings, CurrentUser, Jobs, Storage
from app.enums import AnalysisType
from app.models import Analysis
from app.providers.storage.base import ObjectNotFoundError
from app.schemas.ai import AIDetectionResponse
from app.schemas.analysis import (
    MAX_TITLE_LENGTH,
    AnalysisCounts,
    AnalysisCreatedResponse,
    AnalysisFileResponse,
    AnalysisListResponse,
    AnalysisResponse,
    AnalysisStepResponse,
)
from app.schemas.fingerprints import (
    FingerprintsResponse,
    ImageFingerprintsResponse,
    SimilarAnalysisResponse,
    SimilarTextResponse,
    TextFingerprintsResponse,
    TextFingerprintsValues,
)
from app.schemas.forensics import (
    ELAFindingResponse,
    ForensicArtifactResponse,
    ForensicSkipped,
    ImageForensicsResponse,
)
from app.schemas.matches import SourceMatchesResponse, SourceMatchResponse
from app.schemas.metadata import ImageMetadataResponse, NormalizedMetadataResponse
from app.schemas.provenance import ImageProvenanceResponse, NormalizedProvenanceResponse
from app.schemas.provider_calls import ProviderCallResponse, ProviderCallsResponse
from app.schemas.text import LanguageResponse, TextAnalysisCreate, TextAnalysisResponse
from app.services.image import ImageTooLargeError
from app.services.image.provenance import NormalizedProvenance, provenance_limitations
from app.utils.errors import NotFoundError

router = APIRouter(prefix="/analysis")

MAX_PAGE_SIZE = 100
_CHUNK = 1024 * 1024


async def _read_capped(upload: UploadFile, max_bytes: int) -> bytes:
    """Read the upload without ever buffering more than the cap (+1 byte to detect overflow)."""
    chunks: list[bytes] = []
    total = 0
    while chunk := await upload.read(_CHUNK):
        total += len(chunk)
        if total > max_bytes:
            raise ImageTooLargeError(
                f"The file exceeds the maximum upload size of {max_bytes // (1024 * 1024)} MB."
            )
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/image", response_model=AnalysisCreatedResponse, status_code=status.HTTP_201_CREATED)
async def create_image_analysis(
    user: CurrentUser,
    analyses: AnalysisSvc,
    settings: AppSettings,
    jobs: Jobs,
    file: Annotated[UploadFile, File()],
    title: Annotated[str | None, Form(max_length=MAX_TITLE_LENGTH)] = None,
) -> AnalysisCreatedResponse:
    """Accept one image (JPEG/PNG/WebP/TIFF). Filename and MIME are treated as untrusted."""
    data = await _read_capped(file, settings.max_upload_bytes)
    analysis = await analyses.create_image_analysis(
        user, data=data, filename=file.filename, title=title
    )
    jobs.dispatch(analysis.id)
    return AnalysisCreatedResponse(id=analysis.id, status=analysis.status, type=analysis.type)


@router.post("/text", response_model=AnalysisCreatedResponse, status_code=status.HTTP_201_CREATED)
async def create_text_analysis(
    body: TextAnalysisCreate, user: CurrentUser, analyses: AnalysisSvc, jobs: Jobs
) -> AnalysisCreatedResponse:
    """Accept pasted text (JSON). The original is stored exactly as received."""
    analysis = await analyses.create_text_analysis(user, text=body.text, title=body.title)
    jobs.dispatch(analysis.id)
    return AnalysisCreatedResponse(id=analysis.id, status=analysis.status, type=analysis.type)


_TEXT_NOTES = [
    "Statistics describe the text; they cannot establish who or what wrote it.",
    "Language detection is a statistical guess with an uncalibrated probability.",
    "Hidden or formatting characters are reported and removed only in the normalised copy; "
    "the original is preserved unchanged.",
]
_EXCERPT_CHARS = 4000


@router.get("/{analysis_id}/text", response_model=TextAnalysisResponse)
async def get_analysis_text(
    analysis_id: uuid.UUID, user: CurrentUser, analyses: AnalysisSvc, storage: Storage
) -> TextAnalysisResponse:
    row = await analyses.get_text_analysis(user, analysis_id)
    if row is None:
        raise NotFoundError("Text analysis is not available for this analysis.")
    analysis = await analyses.get_owned(user, analysis_id)
    original = ""
    original_sha = None
    if analysis.files:
        original_sha = analysis.files[0].sha256
        try:
            data, _ = await storage.get(analysis.files[0].object_key)
            original = data.decode("utf-8", "replace")
        except ObjectNotFoundError:
            original = ""
    truncated = len(original) > _EXCERPT_CHARS or len(row.normalized_text) > _EXCERPT_CHARS
    return TextAnalysisResponse(
        original_excerpt=original[:_EXCERPT_CHARS],
        normalized_excerpt=row.normalized_text[:_EXCERPT_CHARS],
        excerpt_chars=_EXCERPT_CHARS,
        truncated=truncated,
        original_sha256=original_sha,
        normalized_sha256=row.normalized_sha256,
        normalization=row.normalization_json or {},
        language=LanguageResponse.model_validate(row.language_json) if row.language_json else None,
        statistics=row.statistics_json or {},
        structure=row.structure_json or {},
        limitations=_TEXT_NOTES,
    )


@router.get("", response_model=AnalysisListResponse)
async def list_analyses(
    user: CurrentUser,
    analyses: AnalysisSvc,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=MAX_PAGE_SIZE),
) -> AnalysisListResponse:
    items, total = await analyses.list_owned(user, page=page, page_size=page_size)
    return AnalysisListResponse(
        items=[_to_response(a) for a in items], page=page, page_size=page_size, total=total
    )


@router.get("/counts", response_model=AnalysisCounts)
async def analysis_counts(user: CurrentUser, analyses: AnalysisSvc) -> AnalysisCounts:
    return AnalysisCounts(**await analyses.counts(user))


@router.get("/{analysis_id}", response_model=AnalysisResponse)
async def get_analysis(
    analysis_id: uuid.UUID, user: CurrentUser, analyses: AnalysisSvc
) -> AnalysisResponse:
    return _to_response(await analyses.get_owned(user, analysis_id))


_CORE_GROUPS = {"EXIF", "XMP", "IPTC", "ICC_Profile"}
_NO_METADATA_NOTE = (
    "No embedded metadata was found. This does not establish whether the file was edited."
)
_RECORDED_NOTE = (
    "Metadata values are recorded by software and can be altered; they are not verified facts."
)
_PILLOW_NOTE = "Extracted with Pillow (reduced coverage): MakerNotes and IPTC were not decoded."


@router.get("/{analysis_id}/metadata", response_model=ImageMetadataResponse)
async def get_analysis_metadata(
    analysis_id: uuid.UUID, user: CurrentUser, analyses: AnalysisSvc
) -> ImageMetadataResponse:
    row = await analyses.get_metadata(user, analysis_id)
    if row is None:
        raise NotFoundError("Metadata has not been extracted for this analysis.")
    normalized = NormalizedMetadataResponse.model_validate(row.normalized_json or {})
    raw = row.raw_json or {}
    limitations = [_RECORDED_NOTE]
    if not (normalized.has_exif or normalized.has_xmp or normalized.has_iptc):
        limitations.append(_NO_METADATA_NOTE)
    if row.engine == "pillow":
        limitations.append(_PILLOW_NOTE)
    return ImageMetadataResponse(
        normalized=normalized,
        exif=row.exif_json or {},
        xmp=row.xmp_json or {},
        iptc=row.iptc_json or {},
        icc=row.icc_json or {},
        other={g: tags for g, tags in raw.items() if g not in _CORE_GROUPS},
        limitations=limitations,
    )


_FINGERPRINT_NOTES = [
    "Identical SHA-256 means identical bytes. A near match means the pictures look alike "
    "(recompression, resizing, light edits); it does not say which came first or where the "
    "image originated.",
    "Only your own analyses are compared. Web-scale reverse search is a separate step.",
]


_TEXT_FINGERPRINT_NOTES = [
    "Identical hashes mean identical text (bytes, after normalisation, or after ignoring case "
    "and punctuation). A near match means many shared 5-word sequences; it does not say which "
    "text came first or whether one was copied from the other.",
    "Only your own analyses are compared. Web-scale phrase search is a separate step.",
]


@router.get(
    "/{analysis_id}/fingerprints",
    response_model=ImageFingerprintsResponse | TextFingerprintsResponse,
)
async def get_analysis_fingerprints(
    analysis_id: uuid.UUID, user: CurrentUser, analyses: AnalysisSvc, settings: AppSettings
) -> ImageFingerprintsResponse | TextFingerprintsResponse:
    analysis = await analyses.get_owned(user, analysis_id)
    if analysis.type == AnalysisType.TEXT:
        tfp = await analyses.get_text_fingerprints(user, analysis_id)
        if tfp is None:
            raise NotFoundError("Fingerprints have not been computed for this analysis.")
        return TextFingerprintsResponse(
            fingerprints=TextFingerprintsValues.model_validate(tfp),
            near_threshold=settings.text_near_threshold,
            similar=[
                SimilarTextResponse(
                    analysis_id=other.id,
                    title=other.title,
                    created_at=other.created_at,
                    relation=relation,
                    estimated_jaccard=round(jaccard, 4),
                )
                for other, relation, jaccard in await analyses.find_similar_texts(user, tfp)
            ],
            limitations=_TEXT_FINGERPRINT_NOTES,
        )
    fp = await analyses.get_fingerprints(user, analysis_id)
    if fp is None:
        raise NotFoundError("Fingerprints have not been computed for this analysis.")
    similar = [
        SimilarAnalysisResponse(
            analysis_id=other.id,
            title=other.title,
            created_at=other.created_at,
            relation=match.relation,
            sha256_match=match.sha256_match,
            phash_distance=match.phash_distance,
            dhash_distance=match.dhash_distance,
            ahash_distance=match.ahash_distance,
        )
        for other, match in await analyses.find_similar(user, fp)
    ]
    return ImageFingerprintsResponse(
        fingerprints=FingerprintsResponse.model_validate(fp),
        near_threshold=settings.fingerprint_near_threshold,
        similar=similar,
        limitations=_FINGERPRINT_NOTES,
    )


_FORENSICS_NOTES = [
    "Forensic methods are heuristics. Each reports what it observed, how confident the method "
    "is by design, and its known failure modes. None of them proves manipulation on its own.",
    "Related signals (ELA, compression, noise) are correlated and are not counted as independent "
    "evidence.",
]


@router.get("/{analysis_id}/forensics", response_model=ImageForensicsResponse)
async def get_analysis_forensics(
    analysis_id: uuid.UUID, user: CurrentUser, analyses: AnalysisSvc, settings: AppSettings
) -> ImageForensicsResponse:
    row = await analyses.get_forensics(user, analysis_id)
    if row is None:
        raise NotFoundError("Forensic analysis has not been run for this analysis.")
    skipped: list[ForensicSkipped] = []
    ela_finding: ELAFindingResponse | None = None
    if row.ela_json:
        if row.ela_json.get("applicable"):
            ela_finding = ELAFindingResponse.model_validate(row.ela_json)
        else:
            skipped.append(ForensicSkipped(method="ela", reason=str(row.ela_json.get("reason"))))
    artifacts = [
        ForensicArtifactResponse(
            name=str(a.get("name")),
            method=str(a.get("method")),
            content_type=str(a.get("content_type")),
            width=int(a.get("width") or 0),
            height=int(a.get("height") or 0),
            url=url,
            expires_in_seconds=settings.signed_url_ttl_seconds,
        )
        for a, url in await analyses.forensic_artifact_links(row)
    ]
    return ImageForensicsResponse(
        ela=ela_finding, skipped=skipped, artifacts=artifacts, limitations=_FORENSICS_NOTES
    )


@router.get("/{analysis_id}/ai", response_model=AIDetectionResponse)
async def get_analysis_ai(
    analysis_id: uuid.UUID, user: CurrentUser, analyses: AnalysisSvc
) -> AIDetectionResponse:
    row = await analyses.get_ai_detection(user, analysis_id)
    if row is None:
        raise NotFoundError("No AI-generation signal was evaluated for this analysis.")
    if row.score is None:
        level = "UNKNOWN"
    elif row.score >= row.threshold_high:
        level = "PROBABLE"
    elif row.score >= row.threshold_medium:
        level = "POSSIBLE"
    else:
        level = "UNKNOWN"
    return AIDetectionResponse(
        modality=row.modality,
        provider=row.provider,
        model=row.model,
        provider_version=row.provider_version,
        score=row.score,
        label=row.label,
        calibrated=row.calibrated,
        cached=row.cached,
        latency_ms=row.latency_ms,
        evaluated_at=row.created_at,
        thresholds={"high": row.threshold_high, "medium": row.threshold_medium},
        evidence_level=level,
        raw=row.raw_json or {},
        limitations=[str(x) for x in (row.limitations_json or [])],
    )


@router.get("/{analysis_id}/matches", response_model=SourceMatchesResponse)
async def get_analysis_matches(
    analysis_id: uuid.UUID, user: CurrentUser, analyses: AnalysisSvc
) -> SourceMatchesResponse:
    run, matches = await analyses.get_source_search(user, analysis_id)
    if run is None:
        raise NotFoundError("No source search was performed for this analysis.")
    return SourceMatchesResponse(
        modality=run.modality,
        provider=run.provider,
        provider_version=run.provider_version,
        searched_at=run.created_at,
        queried_phrases=[str(p) for p in (run.queried_phrases_json or [])],
        matches=[
            SourceMatchResponse(
                rank=m.rank,
                provider=m.provider,
                url=m.url,
                title=m.title,
                snippet=m.snippet,
                similarity=m.similarity,
                source_kind=m.source_kind,
                matched_phrase=m.matched_phrase,
                published_at=m.published_at,
                discovered_at=m.discovered_at,
                raw=m.raw_json or {},
            )
            for m in matches
        ],
        limitations=[str(x) for x in (run.limitations_json or [])],
    )


@router.get("/{analysis_id}/provider-calls", response_model=ProviderCallsResponse)
async def get_analysis_provider_calls(
    analysis_id: uuid.UUID, user: CurrentUser, analyses: AnalysisSvc
) -> ProviderCallsResponse:
    """Audit trail of engine/provider calls for one analysis (owner only)."""
    calls, total = await analyses.list_provider_calls(user, analysis_id)
    return ProviderCallsResponse(
        calls=[ProviderCallResponse.model_validate(c) for c in calls],
        total_estimated_cost=round(total, 6),
    )


@router.get("/{analysis_id}/provenance", response_model=ImageProvenanceResponse)
async def get_analysis_provenance(
    analysis_id: uuid.UUID, user: CurrentUser, analyses: AnalysisSvc
) -> ImageProvenanceResponse:
    row = await analyses.get_provenance(user, analysis_id)
    if row is None:
        raise NotFoundError("Provenance has not been inspected for this analysis.")
    normalized = NormalizedProvenanceResponse.model_validate(row.normalized_json or {})
    limitations = provenance_limitations(NormalizedProvenance(**(row.normalized_json or {})))
    return ImageProvenanceResponse(
        normalized=normalized,
        manifests=row.manifests_json or {},
        validation_status=(row.validation_json or {}).get("status", []),
        limitations=limitations,
    )


@router.delete("/{analysis_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_analysis(analysis_id: uuid.UUID, user: CurrentUser, analyses: AnalysisSvc) -> None:
    await analyses.soft_delete(user, analysis_id)


def _to_response(analysis: Analysis) -> AnalysisResponse:
    response = AnalysisResponse.model_validate(analysis)
    if analysis.files:
        response.file = AnalysisFileResponse.model_validate(analysis.files[0])
    response.steps = [AnalysisStepResponse.model_validate(s) for s in analysis.steps]
    return response
