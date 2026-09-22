"""Final pipeline step: normalise every persisted observation into evidence records."""

from app.models import Evidence, TimelineEvent
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
    synthesis_confidence,
)
from app.services.evidence.timeline import TIMELINE_VERSION, build_timeline


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
        obs = Observations(
            analysis_type=str(analysis.type), file=ctx.file, submitted_at=analysis.created_at
        )
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

        thresholds = EvidenceThresholds.from_settings(ctx.settings)
        drafts = build_evidence(obs, thresholds)
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

        # Timeline: derived from the same drafts; events point at the evidence rows by id.
        ids_by_rule: dict[str, list[str]] = {}
        for d, row in zip(drafts, rows, strict=True):
            ids_by_rule.setdefault(d.rule, []).append(str(row.id))
        events = build_timeline(obs, drafts)
        await repo.replace_timeline(
            aid,
            [
                TimelineEvent(
                    analysis_id=aid,
                    event_type=e.event_type,
                    event_time=e.event_time,
                    raw_time=(e.raw_time or "")[:64] or None,
                    tz_known=e.tz_known,
                    certainty=str(e.certainty),
                    description=e.description,
                    source=e.source[:64],
                    source_evidence_ids=[i for r in e.source_rules for i in ids_by_rule.get(r, [])],
                    details={"version": TIMELINE_VERSION, "rules": list(e.source_rules), **e.data},
                )
                for e in events
            ],
        )
        ctx.artifacts["timeline"] = events
        counts = summarise(drafts)
        return StepOutcome.ok(
            engine_version=ENGINE_VERSION,
            records=len(rows),
            conflicts=sum(1 for d in drafts if d.kind == "conflict"),
            synthesis_confidence=synthesis_confidence(
                [(d.level, d.confidence, d.kind) for d in drafts], thresholds
            ),
            thresholds=thresholds.to_json(),
            timeline_events=len(events),
            timeline_undated=sum(1 for e in events if e.event_time is None),
            **{level.lower(): n for level, n in counts.items()},
        )
