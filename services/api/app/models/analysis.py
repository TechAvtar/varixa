import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.enums import AnalysisStatus
from app.models.base import Base, CreatedAtMixin, TZDateTime, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.analysis_step import AnalysisStep
    from app.models.evidence import Evidence
    from app.models.image_metadata import ImageMetadata
    from app.models.provider_call import ProviderCall
    from app.models.user import User


class Analysis(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "analyses"
    __table_args__ = (Index("ix_analyses_user_id_created_at", "user_id", "created_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=AnalysisStatus.QUEUED, index=True
    )
    title: Mapped[str | None] = mapped_column(String(300))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    retention_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    completed_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    deleted_at: Mapped[datetime | None] = mapped_column(TZDateTime)

    user: Mapped["User"] = relationship(back_populates="analyses")
    files: Mapped[list["AnalysisFile"]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan"
    )
    steps: Mapped[list["AnalysisStep"]] = relationship(
        back_populates="analysis",
        cascade="all, delete-orphan",
        order_by="AnalysisStep.position",
    )
    evidence: Mapped[list["Evidence"]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan"
    )
    provider_calls: Mapped[list["ProviderCall"]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan"
    )
    image_metadata: Mapped["ImageMetadata | None"] = relationship(
        back_populates="analysis", cascade="all, delete-orphan", uselist=False
    )


class AnalysisFile(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "analysis_files"

    analysis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Storage key is internal; never exposed to clients directly.
    object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String(255))
    mime_type: Mapped[str | None] = mapped_column(String(127))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)

    analysis: Mapped["Analysis"] = relationship(back_populates="files")
