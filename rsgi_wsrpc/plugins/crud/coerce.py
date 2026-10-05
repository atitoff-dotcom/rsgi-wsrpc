# -*- coding: utf-8 -*-
"""
Приведение и строгая валидация типов значений ячеек для CRUD-плагина rsgi-wsrpc.
"""

from __future__ import annotations
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Optional
import orjson

from rsgi_wsrpc.core.session import RPCError
from .meta import FieldMeta


def coerce_value(field_meta: FieldMeta, value: Any) -> Any:
    """
    Приводит и валидирует значение от клиента в соответствии с типом колонки.
    В случае несоответствия типов выбрасывает RPCError(-32602, ...).
    """
    field_name = field_meta.name

    # 1. Проверка на None / null
    if value is None:
        if not field_meta.nullable and not field_meta.primary_key:
            raise RPCError(-32602, f"Поле '{field_name}' не может быть пустым (null)")
        return None

    # 2. Булевы значения
    if field_meta.type == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            if value == 1:
                return True
            if value == 0:
                return False
        if isinstance(value, str):
            val_lower = value.strip().lower()
            if val_lower in ("true", "1", "yes", "t", "y"):
                return True
            if val_lower in ("false", "0", "no", "f", "n"):
                return False
        raise RPCError(-32602, f"Поле '{field_name}': некорректное булево значение: {value!r}")

    # 3. Целочисленные значения
    if field_meta.type == "integer":
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        if isinstance(value, str):
            val_str = value.strip()
            try:
                return int(val_str)
            except ValueError:
                pass
        raise RPCError(-32602, f"Поле '{field_name}': значение должно быть целым числом, получено {value!r}")

    # 4. Дробные / Decimal числа
    if field_meta.type == "decimal":
        if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
            return value
        if isinstance(value, str):
            try:
                return float(value.strip())
            except ValueError:
                pass
        raise RPCError(-32602, f"Поле '{field_name}': значение должно быть числом, получено {value!r}")

    # 5. Дата / время (ISO)
    if field_meta.type == "datetime":
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            val_str = value.strip()
            if val_str.endswith("Z"):
                val_str = val_str[:-1] + "+00:00"
            try:
                dt = datetime.fromisoformat(val_str)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except (ValueError, TypeError):
                pass
        raise RPCError(-32602, f"Поле '{field_name}': ожидается дата и время в формате ISO, получено {value!r}")

    # 6. Дата (ISO YYYY-MM-DD)
    if field_meta.type == "date":
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, str):
            try:
                return date.fromisoformat(value.strip())
            except (ValueError, TypeError):
                pass
        raise RPCError(-32602, f"Поле '{field_name}': ожидается дата в формате YYYY-MM-DD, получено {value!r}")

    # 7. Enum
    if field_meta.type == "enum" and field_meta.options:
        str_val = str(value)
        if str_val not in field_meta.options:
            raise RPCError(
                -32602,
                f"Поле '{field_name}': недопустимое значение {value!r}. Доступны: {', '.join(map(str, field_meta.options))}"
            )
        return str_val

    # 8. JSON
    if field_meta.type == "json":
        if isinstance(value, (dict, list)):
            return value
        if isinstance(value, str):
            try:
                return orjson.loads(value)
            except Exception:
                raise RPCError(-32602, f"Поле '{field_name}': некорректный JSON")
        raise RPCError(-32602, f"Поле '{field_name}': ожидается JSON объект или массив")

    # 9. Строка (string)
    if field_meta.type == "string":
        if isinstance(value, str):
            return value
        return str(value)

    return value
