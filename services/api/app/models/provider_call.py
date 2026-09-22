import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin, PortableJSON, TZDateTime, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.analysis import Analysis


class ProviderCall(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Audit record for every external provider call (never stores secrets)."""

    __tablename__ = "provider_calls"

    analysis_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    model_version: Mapped[str | None] = mapped_column(String(128))
    request_id: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    estimated_cost: Mapped[float | None] = mapped_column(Numeric(12, 6))
    request_hash: Mapped[str | None] = mapped_column(String(64))
    response_json: Mapped[dict[str, Any] | None] = mapped_column(PortableJSON)
    error_json: Mapped[dict[str, Any] | None] = mapped_column(PortableJSON)
    # Raw response/error cleared by retention; provider, status and timings remain.
    purged_at: Mapped[datetime | None] = mapped_column(TZDateTime)

    analysis: Mapped["Analysis | None"] = relationship(back_populates="provider_calls")
