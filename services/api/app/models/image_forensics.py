import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin, PortableJSON, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.analysis import Analysis


class ImageForensics(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Structured forensic observations, one column per method. One row per analysis.

    Each ``*_json`` holds ``{method, version, applicable, observation, confidence,
    limitations, ...metrics}`` and is null until that method has run. ``artifacts_json``
    lists generated visualisations by internal object key (never exposed as-is).
    """

    __tablename__ = "image_forensics"

    analysis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    ela_json: Mapped[dict[str, Any] | None] = mapped_column(PortableJSON)
    noise_json: Mapped[dict[str, Any] | None] = mapped_column(PortableJSON)
    compression_json: Mapped[dict[str, Any] | None] = mapped_column(PortableJSON)
    resampling_json: Mapped[dict[str, Any] | None] = mapped_column(PortableJSON)
    copy_move_json: Mapped[dict[str, Any] | None] = mapped_column(PortableJSON)
    statistics_json: Mapped[dict[str, Any] | None] = mapped_column(PortableJSON)
    # [{"name", "method", "object_key", "content_type", "width", "height"}]
    artifacts_json: Mapped[list[dict[str, Any]] | None] = mapped_column(PortableJSON)

    analysis: Mapped["Analysis"] = relationship(back_populates="image_forensics")
