# -*- coding: utf-8 -*-
"""
Метаданные моделей и полей для CRUD-плагина rsgi-wsrpc.
Интроспектирует DeclarativeBase SQLAlchemy и внутренний класс class Crud.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Set, Type
import fnmatch
from sqlalchemy import inspect
from sqlalchemy.orm import Mapper


SENSITIVE_PATTERNS = ("*password*", "*_hash", "*secret*", "*token*", "*private_key*")


def is_sensitive_field(field_name: str) -> bool:
    """Проверяет, является ли поле конфиденциальным (пароли, хэши, токены, секреты)."""
    field_lower = field_name.lower()
    return any(fnmatch.fnmatch(field_lower, pattern) for pattern in SENSITIVE_PATTERNS)


def map_column_type(sa_type: Any) -> str:
    """Отображает тип SQLAlchemy в тип, понятный фронтенду."""
    type_name = type(sa_type).__name__.lower()

    if "int" in type_name:
        return "integer"
    elif "bool" in type_name:
        return "boolean"
    elif "float" in type_name or "numeric" in type_name or "decimal" in type_name:
        return "decimal"
    elif "datetime" in type_name or "timestamp" in type_name:
        return "datetime"
    elif "date" in type_name:
        return "date"
    elif "json" in type_name:
        return "json"
    elif "enum" in type_name:
        return "enum"
    return "string"


@dataclass
class FieldMeta:
    name: str
    type: str
    label: str
    primary_key: bool = False
    nullable: bool = True
    read_only: bool = False
    protected: bool = False
    hidden: bool = False
    searchable: bool = False
    widget: Optional[str] = None
    options: Optional[List[Any]] = None
    foreign_key: Optional[Dict[str, Any]] = None

    def to_schema_dict(self, can_update: bool = True) -> Dict[str, Any]:
        """Сериализация поля в JSON-схему для фронтенда."""
        is_editable = (not self.read_only) and can_update
        data: Dict[str, Any] = {
            "name": self.name,
            "type": self.type,
            "label": self.label,
            "primary_key": self.primary_key,
            "nullable": self.nullable,
            "read_only": self.read_only,
            "protected": self.protected,
            "editable": is_editable,
            "searchable": self.searchable,
        }
        if self.widget:
            data["widget"] = self.widget
        if self.options is not None:
            data["options"] = self.options
        if self.foreign_key:
            data["type"] = "fk"
            data["foreign_key"] = self.foreign_key
        return data


@dataclass
class ModelMeta:
    key: str
    table_name: str
    model_cls: Type[Any]
    verbose_name: str
    verbose_name_plural: str
    is_row_secure: bool
    is_archivable: bool
    fields: Dict[str, FieldMeta] = field(default_factory=dict)
    hidden_fields: Set[str] = field(default_factory=set)
    readonly_fields: Set[str] = field(default_factory=set)
    protected_fields: Set[str] = field(default_factory=set)

    def get_public_fields(self) -> List[FieldMeta]:
        """Возвращает список только открытых (не скрытых) полей."""
        return [f for f in self.fields.values() if not f.hidden]

    def to_schema_dict(self, permissions: Dict[str, bool]) -> Dict[str, Any]:
        """Сериализует модель в схему для фронтенда с учетом прав пользователя."""
        can_update = permissions.get("can_update", False)
        public_fields = [f.to_schema_dict(can_update=can_update) for f in self.get_public_fields()]

        return {
            "key": self.key,
            "table_name": self.table_name,
            "verbose_name": self.verbose_name,
            "verbose_name_plural": self.verbose_name_plural,
            "is_row_secure": self.is_row_secure,
            "is_archivable": self.is_archivable,
            "permissions": permissions,
            "fields": public_fields,
        }


def build_model_meta(cls: Type[Any]) -> ModelMeta:
    """
    Интроспектирует SQLAlchemy-модель и собирает неизменяемый объект ModelMeta.
    Вызывается один раз на старте системы.
    """
    model_name = cls.__name__
    mapper: Mapper = inspect(cls)
    table = mapper.local_table

    # Чтение настроек из внутреннего class Crud (если объявлен)
    crud_cfg = getattr(cls, "Crud", None)
    cfg_hidden = set(getattr(crud_cfg, "hidden", set()) or set())
    cfg_readonly = set(getattr(crud_cfg, "readonly", set()) or set())
    cfg_protected = set(getattr(crud_cfg, "protected", set()) or set())

    # Названия
    v_name = getattr(crud_cfg, "verbose_name", None) or model_name
    v_name_plural = getattr(crud_cfg, "verbose_name_plural", None) or f"{v_name}s"

    col_names = {c.name for c in table.columns}
    is_row_secure = any(c in col_names for c in ("creator_id", "owner_id", "team_id"))
    is_archivable = "is_archived" in col_names

    # По умолчанию для моделей с владением поля владения защищены (требуют права transfer)
    if is_row_secure and not cfg_protected:
        cfg_protected = {"owner_id", "team_id", "creator_id"}.intersection(col_names)

    fields_map: Dict[str, FieldMeta] = {}

    for col in table.columns:
        col_name = col.name
        col_type = map_column_type(col.type)
        is_pk = bool(col.primary_key)

        # Конфиденциальные поля скрыты всегда
        is_hidden = col_name in cfg_hidden or is_sensitive_field(col_name)

        # Read-only поля: PK, временные метки, creator_id или заданные в Crud.readonly
        is_readonly = is_pk or col_name in ("created_at", "updated_at", "creator_id") or col_name in cfg_readonly

        is_protected = col_name in cfg_protected

        info = getattr(col, "info", {}) or {}
        label = info.get("label") or col.comment or col_name.replace("_", " ").capitalize()

        # Определение виджета
        widget = None
        if "widget" in info:
            widget = info["widget"]
        elif col_name.endswith("_file_id"):
            widget = "file"
        elif col_name in ("owner_id", "creator_id"):
            widget = "user_select"
        elif col_name == "team_id":
            widget = "team_select"
        elif col_type == "boolean":
            widget = "switch"
        elif col_type in ("datetime", "date"):
            widget = "date_picker"

        # Опции Enum
        options = None
        if "options" in info:
            options = info["options"]
        elif hasattr(col.type, "enums"):
            options = list(col.type.enums)

        # Внешний ключ (Foreign Key)
        fk_meta = None
        if col.foreign_keys:
            fk = list(col.foreign_keys)[0]
            target_col = fk.column
            target_model_name = None
            if hasattr(target_col.table, "name"):
                target_model_name = target_col.table.name
            fk_meta = {
                "target_table": target_col.table.name if hasattr(target_col, "table") else "",
                "target_column": target_col.name,
                "target_model": target_model_name
            }

        is_searchable = col_type in ("string", "integer") and not is_hidden

        fields_map[col_name] = FieldMeta(
            name=col_name,
            type=col_type,
            label=label,
            primary_key=is_pk,
            nullable=bool(col.nullable),
            read_only=is_readonly,
            protected=is_protected,
            hidden=is_hidden,
            searchable=is_searchable,
            widget=widget,
            options=options,
            foreign_key=fk_meta
        )

    return ModelMeta(
        key=model_name,
        table_name=table.name,
        model_cls=cls,
        verbose_name=v_name,
        verbose_name_plural=v_name_plural,
        is_row_secure=is_row_secure,
        is_archivable=is_archivable,
        fields=fields_map,
        hidden_fields=cfg_hidden,
        readonly_fields=cfg_readonly,
        protected_fields=cfg_protected
    )
