# -*- coding: utf-8 -*-
"""
ORM-модель системного реестра файлов (plugins/files/models.py).
Реализует RFC 0005: Universal Metadata Registry (file_metadata).
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from rsgi_wsrpc.plugins.db import Base


class StoredFile(Base):
    """
    Универсальная запись о сохраненном файле в таблице file_metadata.
    """
    __tablename__ = "file_metadata"
    __table_args__ = {"extend_existing": True}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    folder_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    original_name: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    mime_type: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, default="application/octet-stream")
    sha256: Mapped[Optional[str]] = mapped_column(String(64), index=True, nullable=True)
    owner_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    is_public: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    download_token: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now()
    )

    @property
    def url(self) -> str:
        """Публичный URL для раздачи статики через Nginx."""
        return f"/files/{self.folder_hash}/{self.filename}"

    def to_dict(self) -> Dict[str, Any]:
        """Сериализация метаданных файла для WSRPC-ответов."""
        return {
            "id": self.id,
            "file_id": self.id,
            "folder_hash": self.folder_hash,
            "filename": self.filename,
            "original_name": self.original_name or self.filename,
            "size": self.size,
            "mime_type": self.mime_type,
            "sha256": self.sha256,
            "owner_id": self.owner_id,
            "is_public": self.is_public,
            "url": self.url,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return f"<StoredFile id={self.id} folder={self.folder_hash} file={self.filename}>"
