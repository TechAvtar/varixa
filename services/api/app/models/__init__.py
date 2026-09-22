"""SQLAlchemy ORM models (persistence shape). Never returned directly from routes.

Import this package to register every model on ``Base.metadata`` (needed by Alembic).
"""

from app.models.analysis import Analysis, AnalysisFile
from app.models.analysis_step import AnalysisStep
from app.models.base import Base
from app.models.evidence import Evidence
from app.models.provider_call import ProviderCall
from app.models.user import User
from app.models.user_session import UserSession

__all__ = [
    "Analysis",
    "AnalysisFile",
    "AnalysisStep",
    "Base",
    "Evidence",
    "ProviderCall",
    "User",
    "UserSession",
]
