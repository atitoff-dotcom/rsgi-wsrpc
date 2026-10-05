# -*- coding: utf-8 -*-
"""
Реестр метаданных моделей для CRUD-плагина rsgi-wsrpc.
"""

from __future__ import annotations
from typing import Dict, Optional, Type, Set, Any
from .meta import ModelMeta, build_model_meta


# Служебные таблицы, исключаемые из админки по умолчанию
DEFAULT_SYSTEM_BLACKLIST: Set[str] = {
    "CacheTagVersion",
    "RefreshToken",
    "ActiveSession",
    "OAuthAccount",
    "PrefixBankEvent",
}


class ModelRegistry:
    """
    Реестр метаданных моделей CRUD.
    Собирает ModelMeta один раз на этапе инициализации приложения.
    """
    _models: Dict[str, ModelMeta] = {}
    _expose_all: bool = True
    _blacklist: Set[str] = set(DEFAULT_SYSTEM_BLACKLIST)

    @classmethod
    def configure(cls, expose_all: bool = True, blacklist: Optional[Set[str]] = None) -> None:
        cls._expose_all = expose_all
        if blacklist is not None:
            cls._blacklist = set(blacklist)

    @classmethod
    def register(cls, model_class: Type[Any]) -> ModelMeta:
        """Регистрирует отдельную модель в реестре."""
        meta = build_model_meta(model_class)
        cls._models[meta.key] = meta
        return meta

    @classmethod
    def get(cls, model_name: str) -> Optional[ModelMeta]:
        """Возвращает метаданные модели по имени."""
        return cls._models.get(model_name)

    @classmethod
    def all(cls) -> Dict[str, ModelMeta]:
        """Возвращает все зарегистрированные модели."""
        return cls._models

    @classmethod
    def auto_discover(cls, base_cls: Type[Any]) -> None:
        """
        Автоматически находит все mapped-модели в DeclarativeBase SQLAlchemy
        и строит для них ModelMeta.
        """
        registry = getattr(base_cls, "registry", None)
        if not registry:
            return

        for mapper in registry.mappers:
            m_cls = mapper.class_
            name = m_cls.__name__

            if name in cls._blacklist:
                continue

            # Если включен строгий opt-in (expose_all == False), публикуем только с class Crud
            if not cls._expose_all and not hasattr(m_cls, "Crud"):
                continue

            cls.register(m_cls)

    @classmethod
    def clear(cls) -> None:
        """Сброс реестра (для тестов)."""
        cls._models.clear()
