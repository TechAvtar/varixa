import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin, PortableJSON, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.analysis import Analysis


class ImageProvenance(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """C2PA inspection result. One row per analysis; re-runs replace it."""

    __tablename__ = "image_provenance"

    analysis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    engine: Mapped[str] = mapped_column(String(32), nullable=False)
    engine_version: Mapped[str] = mapped_column(String(64), nullable=False)
    has_c2pa: Mapped[bool] = mapped_column(Boolean, nullable=False)
    valid_signature: Mapped[bool | None] = mapped_column(Boolean)
    signer: Mapped[str | None] = mapped_column(String(300))
    signed_at: Mapped[str | None] = mapped_column(String(64))
    claim_generator: Mapped[str | None] = mapped_column(String(300))
    # Trust run (T047): NULL = not evaluated / inconclusive; the list version names which
    # trust list the verdict applied.
    trusted: Mapped[bool | None] = mapped_column(Boolean)
    trust_list_version: Mapped[str | None] = mapped_column(String(64))
    manifests_json: Mapped[dict[str, Any] | None] = mapped_column(PortableJSON)
    claims_json: Mapped[dict[str, Any] | None] = mapped_column(PortableJSON)
    validation_json: Mapped[dict[str, Any] | None] = mapped_column(PortableJSON)
    normalized_json: Mapped[dict[str, Any] | None] = mapped_column(PortableJSON)
    # Complete tool output (summary + detailed), untouched.
    raw_json: Mapped[dict[str, Any] | None] = mapped_column(PortableJSON)

    analysis: Mapped["Analysis"] = relationship(back_populates="image_provenance")
