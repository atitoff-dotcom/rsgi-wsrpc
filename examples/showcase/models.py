# -*- coding: utf-8 -*-
"""
Декларативные модели демонстрационного приложения (Task Tracker).
Использует официальный плагин базы данных фреймворка: plugins.db.Base.
"""

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Boolean, DateTime
from plugins.db import Base


class Task(Base):
    __tablename__ = "showcase_tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(255), nullable=False)
    completed = Column(Boolean, default=False, nullable=False)
    priority = Column(String(20), default="normal", nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "completed": self.completed,
            "priority": self.priority,
            "created_at": self.created_at.strftime("%H:%M:%S") if self.created_at else "",
        }
