import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.analysis import Analysis


class ImageFingerprints(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Content + perceptual hashes. One row per analysis; recomputation replaces it."""

    __tablename__ = "image_fingerprints"

    analysis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    md5: Mapped[str] = mapped_column(String(32), nullable=False)
    phash: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    dhash: Mapped[str] = mapped_column(String(16), nullable=False)
    ahash: Mapped[str] = mapped_column(String(16), nullable=False)
    # Reserved for a vector-store reference (T018+); never populated in MVP image flow yet.
    embedding_id: Mapped[str | None] = mapped_column(String(128))
    algorithm_version: Mapped[str] = mapped_column(String(16), nullable=False)

    analysis: Mapped["Analysis"] = relationship(back_populates="image_fingerprints")
