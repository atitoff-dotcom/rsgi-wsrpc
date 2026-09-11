# -*- coding: utf-8 -*-
"""
WSRPC Tabular Payload Compression (RFC 0002).
Компактная упаковка списков записей в табличный формат [fields, rows]
для устранения дублирования строковых ключей и разгрузки Python GC и сети.
"""

from typing import List, Dict, Any, Optional, Union
from functools import wraps


def pack_tabular(
    items: Union[List[Dict[str, Any]], List[Union[tuple, list]]],
    fields: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Упаковывает список записей (словарей или кортежей) в компактный табличный формат $tabular: true.

    Пример:
        items = [{"id": 1, "title": "A"}, {"id": 2, "title": "B"}]
        pack_tabular(items)
        -> {"$tabular": True, "fields": ["id", "title"], "rows": [[1, "A"], [2, "B"]]}
    """
    if not items:
        return {"$tabular": True, "fields": fields or [], "rows": []}

    first = items[0]
    if isinstance(first, dict):
        # Список словарей
        if fields is None:
            fields = list(first.keys())
        rows = [
            [item.get(f) for f in fields]
            for item in items
        ]
    elif isinstance(first, (list, tuple)):
        # Прямые строки из SQL без промежуточных dict
        if fields is None:
            raise ValueError("Параметр 'fields' обязателен при передаче кортежей/списков")
        rows = [
            list(r) if isinstance(r, (tuple, list)) else [r]
            for r in items
        ]
    else:
        # Неизвестный формат — возвращаем как есть
        return items

    return {
        "$tabular": True,
        "fields": fields,
        "rows": rows,
    }


def unpack_tabular(data: Any) -> Any:
    """
    Распаковывает компактный формат $tabular обратно в список словарей.
    Рекурсивно обходит словари и списки.
    """
    if not data or not isinstance(data, (dict, list)):
        return data

    if isinstance(data, dict):
        if data.get("$tabular") is True and "fields" in data and "rows" in data:
            fields = data["fields"]
            rows = data["rows"]
            return [
                dict(zip(fields, row))
                for row in rows
            ]
        # Рекурсивная распаковка вложенных структур
        return {k: unpack_tabular(v) for k, v in data.items()}

    if isinstance(data, list):
        return [unpack_tabular(item) for item in data]

    return data


def is_tabular(data: Any) -> bool:
    """Проверяет, является ли объект упакованным табличным представлением."""
    return isinstance(data, dict) and data.get("$tabular") is True and "fields" in data and "rows" in data


def tabular_response(fields: Optional[List[str]] = None, key: Optional[str] = None):
    """
    Декоратор для RPC-методов. Автоматически упаковывает возвращаемый список записей.

    Если метод возвращает list, он упаковывается в {"$tabular": True, "fields": [...], "rows": [...]}.
    Если метод возвращает dict с коллекцией (например, key="items" или key="topics"),
    то упаковывается только эта коллекция внутри словаря.
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            result = await func(*args, **kwargs)
            if isinstance(result, list):
                return pack_tabular(result, fields=fields)
            if isinstance(result, dict):
                target_key = key
                if target_key and target_key in result and isinstance(result[target_key], list):
                    result[target_key] = pack_tabular(result[target_key], fields=fields)
                    return result
                # Поиск списка по умолчанию, если key не указан
                for candidate in ("items", "topics", "records", "data", "rows"):
                    if candidate in result and isinstance(result[candidate], list):
                        result[candidate] = pack_tabular(result[candidate], fields=fields)
                        return result
            return result
        return wrapper
    return decorator
