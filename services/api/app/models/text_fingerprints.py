import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin, PortableJSON, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.analysis import Analysis


class TextFingerprints(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Exact/normalised/canonical hashes and a MinHash signature. One row per analysis."""

    __tablename__ = "text_fingerprints"

    analysis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    normalized_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    canonical_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    minhash_json: Mapped[list[Any]] = mapped_column(PortableJSON, nullable=False)
    shingle_count: Mapped[int] = mapped_column(Integer, nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(16), nullable=False)

    analysis: Mapped["Analysis"] = relationship(back_populates="text_fingerprints")
