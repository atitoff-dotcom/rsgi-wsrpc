# -*- coding: utf-8 -*-
import datetime
from typing import Optional
from sqlalchemy import String, Text, DateTime, func, Integer, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from app.system.db import Base


class FileMetadata(Base):
    """
    Модель единого реестра метаданных файлов и Capability Tokens.
    """
    __tablename__ = "file_metadata"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    folder_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    original_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    download_token: Mapped[Optional[str]] = mapped_column(String(512), nullable=True, index=True)
    size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    mime_type: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    owner_id: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_public: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True), server_default=func.now())

    def __str__(self) -> str:
        return f"File #{self.id}: {self.folder_hash}/{self.filename} ({self.size} bytes)"
