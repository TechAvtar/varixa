"""Final pipeline step: normalise every persisted observation into evidence records."""

from app.models import Evidence
from app.repositories.analysis import AnalysisRepository
from app.repositories.provider_calls import ProviderCallRepository
from app.services.analysis.pipeline import PipelineContext, StepOutcome
from app.services.analysis.similar import similar_images, similar_texts
from app.services.evidence.engine import (
    ENGINE_VERSION,
    EvidenceThresholds,
    Observations,
    build_evidence,
    summarise,
)


class EvidenceStep:
    """Reads the rows every earlier step wrote and replaces the analysis' evidence records.

    Non-critical: the observations themselves are already persisted, and a failure
    here must not discard them. Runs last in both pipelines.
    """

    name = "evidence"
    critical = False

    async def run(self, ctx: PipelineContext) -> StepOutcome:
        repo = AnalysisRepository(ctx.session)
        analysis = ctx.analysis
        aid = analysis.id
        obs = Observations(analysis_type=str(analysis.type), file=ctx.file)
        obs.provider_calls = await ProviderCallRepository(ctx.session).list_for_analysis(aid)
        obs.ai = await repo.get_ai_detection(aid)
        obs.search_run, obs.search_matches = await repo.get_source_search(aid)

        if obs.analysis_type == "image":
            obs.metadata = await repo.get_metadata(aid)
            obs.provenance = await repo.get_provenance(aid)
            obs.fingerprints = await repo.get_fingerprints(aid)
            obs.forensics = await repo.get_forensics(aid)
            if obs.fingerprints is not None:
                obs.similar_images = [
                    (other.id, match.relation, match.score)
                    for other, match in await similar_images(
                        repo, ctx.settings, analysis.user_id, obs.fingerprints
                    )
                ]
        else:
            obs.text = await repo.get_text_analysis(aid)
            obs.text_fingerprints = await repo.get_text_fingerprints(aid)
            if obs.text_fingerprints is not None:
                obs.similar_texts = [
                    (other.id, relation, jaccard)
                    for other, relation, jaccard in await similar_texts(
                        repo, ctx.settings, analysis.user_id, obs.text_fingerprints
                    )
                ]

        drafts = build_evidence(obs, EvidenceThresholds.from_settings(ctx.settings))
        rows = [
            Evidence(
                analysis_id=aid,
                category=d.category,
                level=str(d.level),
                claim=d.claim,
                source=d.source,
                confidence=d.confidence,
                details=d.details_json(),
            )
            for d in drafts
        ]
        await repo.replace_evidence(aid, rows)
        ctx.artifacts["evidence"] = drafts
        counts = summarise(drafts)
        return StepOutcome.ok(
            engine_version=ENGINE_VERSION,
            records=len(rows),
            conflicts=sum(1 for d in drafts if d.kind == "conflict"),
            **{level.lower(): n for level, n in counts.items()},
        )
