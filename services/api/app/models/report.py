import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin, PortableJSON, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.analysis import Analysis


class Report(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A rendered export of an analysis. The file lives in private storage under ``object_key``."""

    __tablename__ = "reports"

    analysis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    format: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # completed | failed
    object_key: Mapped[str | None] = mapped_column(String(512))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    sha256: Mapped[str | None] = mapped_column(String(64))
    page_count: Mapped[int | None] = mapped_column(BigInteger)
    # Counts, synthesis confidence, versions: what the export contained, for the listing.
    summary_json: Mapped[dict[str, Any] | None] = mapped_column(PortableJSON)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)

    analysis: Mapped["Analysis"] = relationship(back_populates="reports")
