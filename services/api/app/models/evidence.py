import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin, PortableJSON, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.analysis import Analysis


class Evidence(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One leveled, traceable evidence record. Raw observations live in ``details``."""

    __tablename__ = "evidence"

    analysis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    level: Mapped[str] = mapped_column(String(16), nullable=False)
    claim: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Numeric(5, 4))
    details: Mapped[dict[str, Any] | None] = mapped_column(PortableJSON)

    analysis: Mapped["Analysis"] = relationship(back_populates="evidence")
