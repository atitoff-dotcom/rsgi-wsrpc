# -*- coding: utf-8 -*-
"""
rsgi_wsrpc.core.http: Базовые протокольные утилиты для работы с RSGI HTTP-запросами.
"""

from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs


def extract_header(scope: Any, header_name: str, default: Optional[str] = None) -> Optional[str]:
    """
    Извлекает HTTP-заголовок из RSGI scope в независимом от регистра формате.
    Поддерживает Granian Headers, dict, список кортежей (строк или байтов).
    """
    target = header_name.lower()
    headers = getattr(scope, "headers", None)
    if headers is None and isinstance(scope, dict):
        headers = scope.get("headers")

    if headers is None:
        return default

    # 1. Если это dict или Granian Headers с методом .get()
    if hasattr(headers, "get"):
        val = headers.get(target)
        if val is None:
            val = headers.get(target.encode("latin1"))
        if val is not None:
            return val.decode("latin1") if isinstance(val, bytes) else str(val)

    # 2. Если это список/кортеж пар (k, v) или объект с .items()
    items = headers.items() if hasattr(headers, "items") else headers
    try:
        for k, v in items:
            k_str = k.decode("latin1").lower() if isinstance(k, bytes) else str(k).lower()
            if k_str == target:
                return v.decode("latin1") if isinstance(v, bytes) else str(v)
    except Exception:
        pass

    return default


def extract_query_params(scope: Any) -> Dict[str, str]:
    """
    Извлекает query-параметры из RSGI scope в виде плоского словаря {param: first_value}.
    """
    qs = getattr(scope, "query_string", None)
    if qs is None and isinstance(scope, dict):
        qs = scope.get("query_string", "")

    if isinstance(qs, bytes):
        qs = qs.decode("utf-8", errors="replace")
    elif not isinstance(qs, str):
        qs = str(qs or "")

    parsed = parse_qs(qs)
    return {k: v[0] if v else "" for k, v in parsed.items()}


__all__ = [
    "extract_header",
    "extract_query_params",
]
