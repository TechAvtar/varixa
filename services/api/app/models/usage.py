import uuid
from datetime import date

from sqlalchemy import BigInteger, Date, ForeignKey, Integer, Numeric, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class Usage(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Per-user, per-calendar-month activity counters (docs/03 ``usage``).

    Counters record *activity in the period* (analyses created, bytes uploaded or
    generated, provider cost incurred). Current storage occupancy is computed from the
    live rows instead, so retention and deletion can never leave the number stale.
    """

    __tablename__ = "usage"
    __table_args__ = (UniqueConstraint("user_id", "period_start", name="uq_usage_user_period"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    analyses_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    image_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    text_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reports_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    provider_calls_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    provider_cost: Mapped[float] = mapped_column(Numeric(12, 6), nullable=False, default=0)
    # Bytes uploaded or generated during the period (activity), not current occupancy.
    storage_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
