import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin, PortableJSON, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.analysis import Analysis


class TextAnalysis(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Normalised text plus deterministic measurements. One row per analysis."""

    __tablename__ = "text_analysis"

    analysis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    # The original stays in object storage (AnalysisFile); this is the working copy.
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    normalization_json: Mapped[dict[str, Any] | None] = mapped_column(PortableJSON)
    language: Mapped[str | None] = mapped_column(String(16))
    language_confidence: Mapped[float | None] = mapped_column(Float)
    language_json: Mapped[dict[str, Any] | None] = mapped_column(PortableJSON)
    word_count: Mapped[int | None] = mapped_column(Integer)
    character_count: Mapped[int | None] = mapped_column(Integer)
    sentence_count: Mapped[int | None] = mapped_column(Integer)
    paragraph_count: Mapped[int | None] = mapped_column(Integer)
    statistics_json: Mapped[dict[str, Any] | None] = mapped_column(PortableJSON)
    structure_json: Mapped[dict[str, Any] | None] = mapped_column(PortableJSON)
    ai_detection_json: Mapped[dict[str, Any] | None] = mapped_column(PortableJSON)
    source_matches_json: Mapped[dict[str, Any] | None] = mapped_column(PortableJSON)
    embedding_ref: Mapped[str | None] = mapped_column(String(128))

    analysis: Mapped["Analysis"] = relationship(back_populates="text_analysis")
