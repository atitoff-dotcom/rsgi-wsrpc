# -*- coding: utf-8 -*-
"""
Конфигурация тестового фреймворка Agrita Backend.
Позволяет переключать цели тестирования (local / stage) через флаги CLI или переменные окружения.
"""

import os
from dataclasses import dataclass

@dataclass
class TargetConfig:
    name: str
    http_url: str
    ws_url: str
    upload_url: str

TARGETS = {
    "stage": TargetConfig(
        name="stage",
        http_url="https://stage.agrita.ru",
        ws_url="wss://stage.agrita.ru/ws",
        upload_url="https://stage.agrita.ru/upload",
    ),
    "local": TargetConfig(
        name="local",
        http_url=os.getenv("TEST_LOCAL_HTTP", "http://127.0.0.1:8080"),
        ws_url=os.getenv("TEST_LOCAL_WS", "ws://127.0.0.1:8080/"),
        upload_url=os.getenv("TEST_LOCAL_UPLOAD", "http://127.0.0.1:8080/upload"),
    ),
}

CURRENT_TARGET = os.getenv("TEST_TARGET", "local")

def get_target(name: str = None) -> TargetConfig:
    key = name or CURRENT_TARGET
    if key not in TARGETS:
        raise ValueError(f"Неизвестная цель тестирования: {key}. Доступны: {list(TARGETS.keys())}")
    return TARGETS[key]
