"""Account-level near-duplicate lookups shared by the API service and the evidence step."""

import uuid

from app.config import Settings
from app.models import Analysis, ImageFingerprints, TextFingerprints
from app.repositories.analysis import AnalysisRepository
from app.services.image.similarity import SimilarityMatch, compare
from app.services.text.fingerprints import estimate_jaccard


async def similar_images(
    repo: AnalysisRepository, settings: Settings, user_id: uuid.UUID, fp: ImageFingerprints
) -> list[tuple[Analysis, SimilarityMatch]]:
    """Exact and near duplicates among the *same user's* live analyses, best first."""
    threshold = settings.fingerprint_near_threshold
    candidates = await repo.list_user_fingerprints(user_id, exclude_analysis_id=fp.analysis_id)
    matches: list[tuple[Analysis, SimilarityMatch]] = []
    for other_fp, other_analysis in candidates:
        match = compare(fp, other_fp, near_threshold=threshold)
        if match is not None:
            matches.append((other_analysis, match))
    matches.sort(key=lambda m: (m[1].score, m[0].created_at), reverse=False)
    return matches


async def similar_texts(
    repo: AnalysisRepository, settings: Settings, user_id: uuid.UUID, fp: TextFingerprints
) -> list[tuple[Analysis, str, float]]:
    """(analysis, relation, estimated_jaccard) among the user's live texts, strongest first."""
    threshold = settings.text_near_threshold
    matches: list[tuple[Analysis, str, float]] = []
    candidates = await repo.list_user_text_fingerprints(user_id, exclude_analysis_id=fp.analysis_id)
    for other, analysis in candidates:
        jaccard = estimate_jaccard(list(fp.minhash_json), list(other.minhash_json))
        if other.sha256 == fp.sha256:
            relation = "exact"
        elif other.normalized_sha256 == fp.normalized_sha256:
            relation = "normalized"
        elif other.canonical_sha256 == fp.canonical_sha256:
            relation = "canonical"
        elif jaccard >= threshold:
            relation = "near"
        else:
            continue
        matches.append((analysis, relation, jaccard))
    rank = {"exact": 0, "normalized": 1, "canonical": 2, "near": 3}
    matches.sort(key=lambda m: (rank[m[1]], -m[2]))
    return matches
