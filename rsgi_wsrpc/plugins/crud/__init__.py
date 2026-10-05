# -*- coding: utf-8 -*-
"""
Официальный плагин универсального реактивного CRUD для rsgi-wsrpc (plugins/crud).
Включает декларативный маппинг моделей, строгую валидацию, capability-based RLS
и встроенную автономную панель управления на Svelte 5.
"""

from .identity import (
    IdentityProvider,
    DefaultIdentityProvider,
    AccessContext,
    create_access_context,
)
from .meta import ModelMeta, FieldMeta, build_model_meta, is_sensitive_field, map_column_type
from .registry import ModelRegistry
from .policy import AccessPolicy, DefaultAccessPolicy
from .coerce import coerce_value
from .events import notify_crud_change
from .handlers import (
    set_identity_provider,
    set_access_policy,
    get_identity_provider,
    get_access_policy,
    handle_crud_schema,
    handle_crud_get,
    handle_crud_list,
    handle_crud_create,
    handle_crud_update_cell,
    handle_crud_bulk_update,
    handle_crud_delete,
    crud_schema,
    crud_get,
    crud_list,
    crud_create,
    crud_update_cell,
    crud_bulk_update,
    crud_delete,
)
from .auth import (
    set_crud_authenticator,
    get_crud_authenticator,
    create_crud_session,
    get_crud_session,
    revoke_crud_session,
)
# Регистрация HTTP-роутов для статики
from . import static_handler  # noqa: F401

__all__ = [
    "IdentityProvider",
    "DefaultIdentityProvider",
    "AccessContext",
    "create_access_context",
    "ModelMeta",
    "FieldMeta",
    "build_model_meta",
    "is_sensitive_field",
    "map_column_type",
    "ModelRegistry",
    "AccessPolicy",
    "DefaultAccessPolicy",
    "coerce_value",
    "notify_crud_change",
    "set_identity_provider",
    "set_access_policy",
    "get_identity_provider",
    "get_access_policy",
    "handle_crud_schema",
    "handle_crud_get",
    "handle_crud_list",
    "handle_crud_create",
    "handle_crud_update_cell",
    "handle_crud_bulk_update",
    "handle_crud_delete",
    "crud_schema",
    "crud_get",
    "crud_list",
    "crud_create",
    "crud_update_cell",
    "crud_bulk_update",
    "crud_delete",
    "set_crud_authenticator",
    "get_crud_authenticator",
    "create_crud_session",
    "get_crud_session",
    "revoke_crud_session",
]
