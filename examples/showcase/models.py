# -*- coding: utf-8 -*-
"""
Declarative models for the Showcase demonstration application.
Uses official framework database plugin: plugins.db.Base
and declarative mapping for plugins.crud (class Crud:).
"""

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text
from plugins.db import Base


class Task(Base):
    __tablename__ = "showcase_tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(255), nullable=False)
    completed = Column(Boolean, default=False, nullable=False)
    priority = Column(String(20), default="normal", nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    class Crud:
        verbose_name = "Task"
        verbose_name_plural = "Tasks"
        readonly = {"created_at"}

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "completed": self.completed,
            "priority": self.priority,
            "created_at": self.created_at.strftime("%H:%M:%S") if self.created_at else "",
        }


class Document(Base):
    __tablename__ = "showcase_documents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(200), nullable=False)
    category = Column(String(50), default="general", nullable=False)
    views = Column(Integer, default=0, nullable=False)
    content = Column(Text, default="", nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    class Crud:
        verbose_name = "Document"
        verbose_name_plural = "Documents"
        readonly = {"updated_at"}

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "category": self.category,
            "views": self.views,
            "content": self.content,
            "updated_at": self.updated_at.strftime("%H:%M:%S") if self.updated_at else "",
        }
