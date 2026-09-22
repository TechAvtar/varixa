import uuid
from typing import Annotated

from fastapi import APIRouter, File, Form, Query, UploadFile, status

from app.api.deps import AnalysisSvc, AppSettings, CurrentUser, Jobs, Storage
from app.models import Analysis
from app.providers.storage.base import ObjectNotFoundError
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
)
from app.schemas.metadata import ImageMetadataResponse, NormalizedMetadataResponse
from app.schemas.provenance import ImageProvenanceResponse, NormalizedProvenanceResponse
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


@router.get("/{analysis_id}/fingerprints", response_model=ImageFingerprintsResponse)
async def get_analysis_fingerprints(
    analysis_id: uuid.UUID, user: CurrentUser, analyses: AnalysisSvc, settings: AppSettings
) -> ImageFingerprintsResponse:
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
