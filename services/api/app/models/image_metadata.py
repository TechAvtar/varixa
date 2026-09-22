import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin, PortableJSON, TZDateTime, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.analysis import Analysis


class ImageMetadata(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Raw metadata groups plus a normalised view. One row per analysis (recomputation replaces)."""

    __tablename__ = "image_metadata"

    analysis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    engine: Mapped[str] = mapped_column(String(32), nullable=False)
    engine_version: Mapped[str] = mapped_column(String(64), nullable=False)
    exif_json: Mapped[dict[str, Any] | None] = mapped_column(PortableJSON)
    xmp_json: Mapped[dict[str, Any] | None] = mapped_column(PortableJSON)
    iptc_json: Mapped[dict[str, Any] | None] = mapped_column(PortableJSON)
    icc_json: Mapped[dict[str, Any] | None] = mapped_column(PortableJSON)
    # Every group the engine returned (including the four above), untouched except size caps.
    raw_json: Mapped[dict[str, Any] | None] = mapped_column(PortableJSON)
    normalized_json: Mapped[dict[str, Any] | None] = mapped_column(PortableJSON)
    software: Mapped[str | None] = mapped_column(String(200))
    camera_make: Mapped[str | None] = mapped_column(String(200))
    camera_model: Mapped[str | None] = mapped_column(String(200))
    # Only set when the metadata carried a timezone; otherwise see normalized_json.
    captured_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    modified_at: Mapped[datetime | None] = mapped_column(TZDateTime)

    analysis: Mapped["Analysis"] = relationship(back_populates="image_metadata")
