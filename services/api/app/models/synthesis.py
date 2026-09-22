import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin, PortableJSON, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.analysis import Analysis


class Synthesis(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """The model's explanation of the evidence, after grounding checks. One row per analysis.

    ``evidence_fingerprint`` identifies the exact evidence set that was explained, so the
    API can flag a synthesis as stale when the evidence has since changed.
    """

    __tablename__ = "syntheses"

    analysis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    model_version: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(16), nullable=False)
    evidence_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    # {section: {text, evidence_ids, dropped_ids, grounded}}
    sections_json: Mapped[dict[str, Any]] = mapped_column(PortableJSON, nullable=False)
    grounded: Mapped[bool] = mapped_column(Boolean, nullable=False)
    warnings_json: Mapped[list[Any] | None] = mapped_column(PortableJSON)
    cited_ids_json: Mapped[list[Any] | None] = mapped_column(PortableJSON)
    cached: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    estimated_cost: Mapped[float | None] = mapped_column(Float)
    raw_json: Mapped[dict[str, Any] | None] = mapped_column(PortableJSON)

    analysis: Mapped["Analysis"] = relationship(back_populates="synthesis")
