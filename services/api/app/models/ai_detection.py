import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin, PortableJSON, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.analysis import Analysis


class AIDetection(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One provider's AI-generation signal for an analysis (image or text).

    Spec table ``image_ai_detection`` generalised to both modalities; the raw
    provider response is preserved for auditability.
    """

    __tablename__ = "ai_detections"

    analysis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    modality: Mapped[str] = mapped_column(String(16), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    provider_version: Mapped[str] = mapped_column(String(64), nullable=False)
    score: Mapped[float | None] = mapped_column(Float)
    label: Mapped[str] = mapped_column(String(32), nullable=False)
    calibrated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cached: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    request_id: Mapped[str | None] = mapped_column(String(128))
    threshold_high: Mapped[float] = mapped_column(Float, nullable=False)
    threshold_medium: Mapped[float] = mapped_column(Float, nullable=False)
    limitations_json: Mapped[list[Any] | None] = mapped_column(PortableJSON)
    raw_json: Mapped[dict[str, Any] | None] = mapped_column(PortableJSON)

    analysis: Mapped["Analysis"] = relationship(back_populates="ai_detection")
