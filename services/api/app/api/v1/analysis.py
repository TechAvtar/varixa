import uuid
from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, File, Form, Query, UploadFile, status

from app.api.deps import AnalysisSvc, AppSettings, CurrentUser, Jobs, Storage
from app.enums import AnalysisType, EvidenceLevel
from app.models import Analysis, Evidence, Synthesis
from app.providers.llm.base import SECTIONS as _SYNTHESIS_SECTIONS
from app.providers.storage.base import ObjectNotFoundError
from app.schemas.ai import AIDetectionResponse
from app.schemas.analysis import (
    MAX_TITLE_LENGTH,
    AnalysisCounts,
    AnalysisCreatedResponse,
    AnalysisFileLinkResponse,
    AnalysisFileResponse,
    AnalysisListResponse,
    AnalysisResponse,
    AnalysisStepResponse,
)
from app.schemas.evidence import EvidenceListResponse, EvidenceRecordResponse
from app.schemas.fingerprints import (
    FingerprintsResponse,
    ImageFingerprintsResponse,
    SimilarAnalysisResponse,
    SimilarTextResponse,
    TextFingerprintsResponse,
    TextFingerprintsValues,
)
from app.schemas.forensics import (
    CompressionFindingResponse,
    CopyMoveFindingResponse,
    DoubleCompressionFindingResponse,
    ELAFindingResponse,
    ForensicArtifactResponse,
    ForensicSkipped,
    ImageForensicsResponse,
    NoiseFindingResponse,
    ResamplingFindingResponse,
    ThumbnailFindingResponse,
)
from app.schemas.matches import (
    SourceMatchesResponse,
    SourceMatchesSummary,
    SourceMatchResponse,
)
from app.schemas.metadata import ImageMetadataResponse, NormalizedMetadataResponse
from app.schemas.overview import (
    OverviewEngine,
    OverviewMethodology,
    OverviewResponse,
    OverviewStep,
)
from app.schemas.provenance import ImageProvenanceResponse, NormalizedProvenanceResponse
from app.schemas.provider_calls import ProviderCallResponse, ProviderCallsResponse
from app.schemas.synthesis import (
    SynthesisCitation,
    SynthesisResponse,
    SynthesisSectionResponse,
)
from app.schemas.text import LanguageResponse, TextAnalysisCreate, TextAnalysisResponse
from app.schemas.timeline import TimelineEventResponse, TimelineResponse
from app.services.evidence.engine import (
    ENGINE_VERSION,
    EvidenceThresholds,
    ai_level,
    synthesis_confidence,
)
from app.services.evidence.timeline import LIMITATIONS as _TIMELINE_NOTES
from app.services.image import ImageTooLargeError
from app.services.image.provenance import NormalizedProvenance, provenance_limitations
from app.services.reports.overview import OVERVIEW_VERSION, build_overview
from app.services.search.summary import summarize_matches
from app.services.synthesis.request import build_request as _build_synthesis_request
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


@router.get("/{analysis_id}/file", response_model=AnalysisFileLinkResponse)
async def get_analysis_file_link(
    analysis_id: uuid.UUID, user: CurrentUser, analyses: AnalysisSvc, settings: AppSettings
) -> AnalysisFileLinkResponse:
    """A short-lived signed link to the stored original, for the owner's own viewer."""
    url, file = await analyses.original_file_link(user, analysis_id)
    return AnalysisFileLinkResponse(
        url=url,
        expires_in_seconds=settings.signed_url_ttl_seconds,
        mime_type=file.mime_type,
        width=file.width,
        height=file.height,
    )


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
    compression_finding: CompressionFindingResponse | None = None
    if row.compression_json:
        if row.compression_json.get("applicable"):
            compression_finding = CompressionFindingResponse.model_validate(row.compression_json)
        else:
            skipped.append(
                ForensicSkipped(
                    method="compression", reason=str(row.compression_json.get("reason"))
                )
            )
    resampling_finding: ResamplingFindingResponse | None = None
    if row.resampling_json:
        if row.resampling_json.get("applicable"):
            resampling_finding = ResamplingFindingResponse.model_validate(row.resampling_json)
        else:
            skipped.append(
                ForensicSkipped(method="resampling", reason=str(row.resampling_json.get("reason")))
            )
    noise_finding: NoiseFindingResponse | None = None
    if row.noise_json:
        if row.noise_json.get("applicable"):
            noise_finding = NoiseFindingResponse.model_validate(row.noise_json)
        else:
            skipped.append(
                ForensicSkipped(method="noise", reason=str(row.noise_json.get("reason")))
            )
    copy_move_finding: CopyMoveFindingResponse | None = None
    if row.copy_move_json:
        if row.copy_move_json.get("applicable"):
            copy_move_finding = CopyMoveFindingResponse.model_validate(row.copy_move_json)
        else:
            skipped.append(
                ForensicSkipped(method="copy_move", reason=str(row.copy_move_json.get("reason")))
            )
    thumbnail_finding: ThumbnailFindingResponse | None = None
    if row.thumbnail_json:
        if row.thumbnail_json.get("applicable"):
            thumbnail_finding = ThumbnailFindingResponse.model_validate(row.thumbnail_json)
        else:
            skipped.append(
                ForensicSkipped(method="thumbnail", reason=str(row.thumbnail_json.get("reason")))
            )
    double_finding: DoubleCompressionFindingResponse | None = None
    if row.double_compression_json:
        if row.double_compression_json.get("applicable"):
            double_finding = DoubleCompressionFindingResponse.model_validate(
                row.double_compression_json
            )
        else:
            skipped.append(
                ForensicSkipped(
                    method="double_compression",
                    reason=str(row.double_compression_json.get("reason")),
                )
            )
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
        ela=ela_finding,
        compression=compression_finding,
        resampling=resampling_finding,
        noise=noise_finding,
        copy_move=copy_move_finding,
        thumbnail=thumbnail_finding,
        double_compression=double_finding,
        skipped=skipped,
        artifacts=artifacts,
        limitations=_FORENSICS_NOTES,
    )


@router.get("/{analysis_id}/ai", response_model=AIDetectionResponse)
async def get_analysis_ai(
    analysis_id: uuid.UUID, user: CurrentUser, analyses: AnalysisSvc
) -> AIDetectionResponse:
    row = await analyses.get_ai_detection(user, analysis_id)
    if row is None:
        raise NotFoundError("No AI-generation signal was evaluated for this analysis.")
    # Same rule as the evidence engine: a high score is PROBABLE only when calibrated.
    level = ai_level(
        row.score,
        calibrated=row.calibrated,
        t=EvidenceThresholds(
            ai_score_high=row.threshold_high, ai_score_medium=row.threshold_medium
        ),
    )
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
        summary=SourceMatchesSummary(**summarize_matches(matches).__dict__),
        limitations=[str(x) for x in (run.limitations_json or [])],
    )


def _evidence_record(r: Evidence) -> EvidenceRecordResponse:
    d = r.details or {}
    return EvidenceRecordResponse(
        id=r.id,
        rule=str(d.get("rule") or ""),
        category=r.category,
        level=EvidenceLevel(r.level),
        kind=d.get("kind") or "signal",
        claim=r.claim,
        source=r.source,
        confidence=float(r.confidence) if r.confidence is not None else None,
        detail=d.get("detail"),
        limitation=d.get("limitation"),
        refs=[str(x) for x in (d.get("refs") or [])],
        provider_version=d.get("provider_version"),
        conflicts_with=[str(x) for x in (d.get("conflicts_with") or [])],
        data=dict(d.get("data") or {}),
        created_at=r.created_at,
    )


@router.get("/{analysis_id}/evidence", response_model=EvidenceListResponse)
async def get_analysis_evidence(
    analysis_id: uuid.UUID, user: CurrentUser, analyses: AnalysisSvc, settings: AppSettings
) -> EvidenceListResponse:
    """Leveled, traceable evidence records produced by the evidence engine (docs/07)."""
    rows = await analyses.list_evidence(user, analysis_id)
    if not rows:
        raise NotFoundError("Evidence has not been generated for this analysis yet.")
    thresholds = EvidenceThresholds.from_settings(settings)
    items: list[EvidenceRecordResponse] = []
    counts = {level.value: 0 for level in EvidenceLevel}
    for r in rows:
        counts[r.level] = counts.get(r.level, 0) + 1
        items.append(_evidence_record(r))
    return EvidenceListResponse(
        engine_version=str((rows[0].details or {}).get("engine_version") or ENGINE_VERSION),
        generated_at=max(r.created_at for r in rows),
        counts=counts,
        conflicts=sum(1 for i in items if i.kind == "conflict"),
        synthesis_confidence=synthesis_confidence(
            [(i.level, i.confidence, i.kind) for i in items], thresholds
        ),
        thresholds=thresholds.to_json(),
        items=items,
    )


@router.get("/{analysis_id}/timeline", response_model=TimelineResponse)
async def get_analysis_timeline(
    analysis_id: uuid.UUID, user: CurrentUser, analyses: AnalysisSvc
) -> TimelineResponse:
    """Evidence-derived timeline: only times some subsystem recorded, each with its certainty."""
    rows = await analyses.list_timeline(user, analysis_id)
    if not rows:
        raise NotFoundError("No timeline has been built for this analysis yet.")
    events = [
        TimelineEventResponse(
            id=r.id,
            event_type=r.event_type,
            event_time=r.event_time,
            raw_time=r.raw_time,
            tz_known=r.tz_known,
            certainty=EvidenceLevel(r.certainty),
            description=r.description,
            source=r.source,
            source_evidence_ids=[uuid.UUID(str(x)) for x in (r.source_evidence_ids or [])],
            data={k: v for k, v in (r.details or {}).items() if k not in {"version", "rules"}},
        )
        for r in rows
    ]
    return TimelineResponse(
        version=str((rows[0].details or {}).get("version") or "v1"),
        generated_at=max(r.created_at for r in rows),
        events=events,
        limitations=list(_TIMELINE_NOTES),
    )


_SYNTHESIS_NOTES = [
    "This text was written by a language model from the evidence records above and nothing "
    "else. It cannot add evidence or change a level; each section lists the records it used.",
    "Sections flagged as ungrounded made statements without citing evidence and should be "
    "read as unsupported. Warnings list wording the checks found questionable.",
    "A synthesis marked not current was produced for an earlier evidence set; re-run the "
    "analysis to refresh it.",
]


@router.get("/{analysis_id}/synthesis", response_model=SynthesisResponse)
async def get_analysis_synthesis(
    analysis_id: uuid.UUID, user: CurrentUser, analyses: AnalysisSvc, settings: AppSettings
) -> SynthesisResponse:
    """The model's grounded explanation of the evidence (docs/07 summary template)."""
    row = await analyses.get_synthesis(user, analysis_id)
    if row is None:
        raise NotFoundError("No synthesis has been generated for this analysis.")
    evidence = await analyses.list_evidence(user, analysis_id)
    return _synthesis_response(row, evidence)


def _synthesis_response(row: Synthesis, evidence: Sequence[Evidence]) -> SynthesisResponse:
    by_id = {str(e.id): e for e in evidence}
    current_fp = _build_synthesis_request(
        analysis_type="",
        evidence_rows=evidence,
        timeline_rows=[],
        synthesis_confidence=0.0,
        prompt_version=row.prompt_version,
    ).fingerprint
    sections = []
    for key, question in _SYNTHESIS_SECTIONS:
        s = (row.sections_json or {}).get(key) or {}
        cites = []
        for eid in s.get("evidence_ids") or []:
            e = by_id.get(str(eid))
            if e is not None:
                cites.append(
                    SynthesisCitation(
                        id=e.id,
                        rule=str((e.details or {}).get("rule") or ""),
                        level=e.level,
                        claim=e.claim,
                    )
                )
        sections.append(
            SynthesisSectionResponse(
                key=key,
                question=question,
                text=str(s.get("text") or ""),
                citations=cites,
                grounded=bool(s.get("grounded", True)),
                dropped_citations=len(s.get("dropped_ids") or []),
            )
        )
    return SynthesisResponse(
        provider=row.provider,
        model=row.model,
        model_version=row.model_version,
        prompt_version=row.prompt_version,
        generated_at=row.created_at,
        current=row.evidence_fingerprint == current_fp,
        grounded=row.grounded,
        warnings=[str(w) for w in (row.warnings_json or [])],
        sections=sections,
        cached=row.cached,
        latency_ms=row.latency_ms,
        tokens_in=row.tokens_in,
        tokens_out=row.tokens_out,
        estimated_cost=row.estimated_cost,
        limitations=_SYNTHESIS_NOTES,
        raw=row.raw_json or {},
    )


@router.get("/{analysis_id}/overview", response_model=OverviewResponse)
async def get_analysis_overview(
    analysis_id: uuid.UUID, user: CurrentUser, analyses: AnalysisSvc, settings: AppSettings
) -> OverviewResponse:
    """The report's first page: grouped evidence, synthesis and methodology from stored rows."""
    analysis = await analyses.get_owned(user, analysis_id)
    evidence = await analyses.list_evidence(user, analysis_id)
    if not evidence:
        raise NotFoundError("Evidence has not been generated for this analysis yet.")
    calls, _ = await analyses.list_provider_calls(user, analysis_id)
    synthesis_row = await analyses.get_synthesis(user, analysis_id)
    draft = build_overview(
        evidence_rows=evidence,
        steps=analysis.steps,
        provider_calls=calls,
        thresholds=EvidenceThresholds.from_settings(settings),
    )
    return OverviewResponse(
        version=OVERVIEW_VERSION,
        generated_at=max(e.created_at for e in evidence),
        counts=draft.counts,
        synthesis_confidence=draft.synthesis_confidence,
        verified=[_evidence_record(r) for r in draft.verified],
        strong=[_evidence_record(r) for r in draft.strong],
        probabilistic=[_evidence_record(r) for r in draft.probabilistic],
        conflicts=[_evidence_record(r) for r in draft.conflicts],
        unknown=[_evidence_record(r) for r in draft.unknown],
        synthesis=_synthesis_response(synthesis_row, evidence) if synthesis_row else None,
        methodology=OverviewMethodology(
            level_definitions=draft.level_definitions,
            notes=draft.methodology,
            steps=[OverviewStep(**s.__dict__) for s in draft.steps],
            engines=[OverviewEngine(**e.__dict__) for e in draft.engines],
            thresholds=draft.thresholds,
        ),
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
        tree=(row.raw_json or {}).get("tree"),
        limitations=limitations,
    )


@router.post("/{analysis_id}/keep", response_model=AnalysisResponse)
async def keep_analysis(
    analysis_id: uuid.UUID, user: CurrentUser, analyses: AnalysisSvc
) -> AnalysisResponse:
    """Keep the raw content beyond the retention window (owner only)."""
    return _to_response(await analyses.keep(user, analysis_id, keep=True))


@router.delete("/{analysis_id}/keep", response_model=AnalysisResponse)
async def release_analysis(
    analysis_id: uuid.UUID, user: CurrentUser, analyses: AnalysisSvc
) -> AnalysisResponse:
    """Let the raw content expire again under the retention policy."""
    return _to_response(await analyses.keep(user, analysis_id, keep=False))


@router.delete("/{analysis_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_analysis(analysis_id: uuid.UUID, user: CurrentUser, analyses: AnalysisSvc) -> None:
    await analyses.soft_delete(user, analysis_id)


def _to_response(analysis: Analysis) -> AnalysisResponse:
    response = AnalysisResponse.model_validate(analysis)
    if analysis.files:
        response.file = AnalysisFileResponse.model_validate(analysis.files[0])
    response.steps = [AnalysisStepResponse.model_validate(s) for s in analysis.steps]
    return response
