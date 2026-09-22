import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin, PortableJSON, TZDateTime, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.analysis import Analysis


class TimelineEvent(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One dated (or undatable) event derived from evidence. Replaced on every run."""

    __tablename__ = "timeline_events"

    analysis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    # Null when the recorded time could not be parsed; the raw string is kept regardless.
    event_time: Mapped[datetime | None] = mapped_column(TZDateTime)
    raw_time: Mapped[str | None] = mapped_column(String(64))
    tz_known: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    certainty: Mapped[str] = mapped_column(String(16), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    # Evidence row ids this event was derived from.
    source_evidence_ids: Mapped[list[Any] | None] = mapped_column(PortableJSON)
    details: Mapped[dict[str, Any] | None] = mapped_column(PortableJSON)

    analysis: Mapped["Analysis"] = relationship(back_populates="timeline_events")
