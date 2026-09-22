import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, PortableJSON, TZDateTime, UUIDPrimaryKeyMixin


class ProviderCacheEntry(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Cached provider result keyed by content hash + provider/operation/model.

    Shared across users on purpose: the key is derived from the content bytes,
    so two users submitting identical content get the same provider answer
    without a second paid call. The payload never contains user identity.
    """

    __tablename__ = "provider_cache"

    cache_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    model_version: Mapped[str] = mapped_column(String(128), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(PortableJSON, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False, index=True)
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_hit_at: Mapped[datetime | None] = mapped_column(TZDateTime)

    @staticmethod
    def new_id() -> uuid.UUID:
        return uuid.uuid4()
