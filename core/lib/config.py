import logging
import os
from typing import Any

import yaml

logger = logging.getLogger("app.config")


def deep_merge(dict1: dict, dict2: dict) -> dict:
    """
    Рекурсивно объединяет два словаря. Значения из dict2 перезаписывают dict1.
    """
    result = dict1.copy()
    for key, value in dict2.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class Settings:
    def __init__(self, data: dict):
        self._data = data

    def __getattr__(self, name) -> Any:
        if name in self._data:
            val = self._data[name]
            if isinstance(val, dict):
                return Settings(val)
            return val
        raise AttributeError(f"Настройка '{name}' не найдена в конфигурации")

    def get(self, name, default=None):
        val = self._data.get(name, default)
        if isinstance(val, dict):
            return Settings(val)
        return val

    def __getitem__(self, name):
        if name in self._data:
            val = self._data[name]
            if isinstance(val, dict):
                return Settings(val)
            return val
        raise KeyError(name)

    def __repr__(self) -> str:
        return f"Settings({self._data!r})"


def load_settings() -> Settings:
    """
    Загружает конфигурационные файлы ядра платформы (core_settings.yaml и core_settings_my.yaml)
    и объединяет их в единый древовидный объект настроек Settings.
    """
    data = {}

    # Определяем корневую директорию проекта относительно расположения этого файла (core/lib/config.py)
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    settings_path = os.path.join(root_dir, "core_settings.yaml")
    my_settings_path = os.path.join(root_dir, "core_settings_my.yaml")

    # 1. Загружаем основной общесистемный core_settings.yaml
    if os.path.exists(settings_path):
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                content = yaml.safe_load(f)
                if isinstance(content, dict):
                    data = content
        except Exception as e:
            logger.error(f"Ошибка при чтении core_settings.yaml: {e}")

    # 2. Загружаем локальный пользовательский core_settings_my.yaml, если он существует
    if os.path.exists(my_settings_path):
        try:
            with open(my_settings_path, "r", encoding="utf-8") as f:
                content_my = yaml.safe_load(f)
                if isinstance(content_my, dict):
                    data = deep_merge(data, content_my)
        except Exception as e:
            logger.error(f"Ошибка при чтении core_settings_my.yaml: {e}")

    return Settings(data)


settings = load_settings()
