"""SQLAlchemy ORM models (persistence shape). Never returned directly from routes.

Import this package to register every model on ``Base.metadata`` (needed by Alembic).
"""

from app.models.ai_detection import AIDetection
from app.models.analysis import Analysis, AnalysisFile
from app.models.analysis_step import AnalysisStep
from app.models.base import Base
from app.models.evidence import Evidence
from app.models.image_fingerprints import ImageFingerprints
from app.models.image_forensics import ImageForensics
from app.models.image_metadata import ImageMetadata
from app.models.image_provenance import ImageProvenance
from app.models.provider_cache import ProviderCacheEntry
from app.models.provider_call import ProviderCall
from app.models.source_match import SourceMatch, SourceSearchRun
from app.models.text_analysis import TextAnalysis
from app.models.text_fingerprints import TextFingerprints
from app.models.timeline_event import TimelineEvent
from app.models.user import User
from app.models.user_session import UserSession

__all__ = [
    "AIDetection",
    "Analysis",
    "AnalysisFile",
    "AnalysisStep",
    "Base",
    "Evidence",
    "ImageFingerprints",
    "ImageForensics",
    "ImageMetadata",
    "ImageProvenance",
    "ProviderCacheEntry",
    "ProviderCall",
    "SourceMatch",
    "SourceSearchRun",
    "TextAnalysis",
    "TextFingerprints",
    "TimelineEvent",
    "User",
    "UserSession",
]
