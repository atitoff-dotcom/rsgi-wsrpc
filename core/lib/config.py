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
    Загружает конфигурационные файлы ядра платформы (settings.yaml / core_settings.yaml)
    из директории фреймворка и текущей рабочей директории приложения (CWD)
    и объединяет их в единый древовидный объект настроек Settings.
    """
    data = {}

    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    cwd = os.getcwd()

    # Кандидаты для последовательной загрузки и переопределения
    candidate_paths = [
        os.path.join(root_dir, "settings.yaml"),
        os.path.join(root_dir, "core_settings.yaml"),
        os.path.join(cwd, "settings.yaml"),
        os.path.join(cwd, "core_settings.yaml"),
        os.path.join(cwd, "core_settings_my.yaml"),
    ]

    for path in candidate_paths:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = yaml.safe_load(f)
                    if isinstance(content, dict):
                        data = deep_merge(data, content)
            except Exception as e:
                logger.error(f"Ошибка при чтении {path}: {e}")

    return Settings(data)


settings = load_settings()
