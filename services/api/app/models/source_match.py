import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin, PortableJSON, TZDateTime, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.analysis import Analysis


class SourceMatch(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One reverse-image or phrase-search hit (spec table ``reverse_matches``)."""

    __tablename__ = "reverse_matches"

    analysis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_version: Mapped[str] = mapped_column(String(64), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    snippet: Mapped[str | None] = mapped_column(Text)
    similarity: Mapped[float | None] = mapped_column(Float)
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    matched_phrase: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[str | None] = mapped_column(String(64))
    discovered_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    raw_json: Mapped[dict[str, Any] | None] = mapped_column(PortableJSON)

    analysis: Mapped["Analysis"] = relationship(back_populates="source_matches")


class SourceSearchRun(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Summary of the search that produced the matches (one per analysis; re-runs replace)."""

    __tablename__ = "source_search_runs"

    analysis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    modality: Mapped[str] = mapped_column(String(16), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_version: Mapped[str] = mapped_column(String(64), nullable=False)
    queried_phrases_json: Mapped[list[Any] | None] = mapped_column(PortableJSON)
    match_count: Mapped[int] = mapped_column(Integer, nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    request_id: Mapped[str | None] = mapped_column(String(128))
    limitations_json: Mapped[list[Any] | None] = mapped_column(PortableJSON)

    analysis: Mapped["Analysis"] = relationship(back_populates="source_search_run")
