# -*- coding: utf-8 -*-
"""
rsgi_wsrpc.compat: Transparent backward-compatibility bridge.

Allows legacy code and existing projects using flat imports
(`import core...`, `import plugins...`) to continue working smoothly
without changes, mapping them to `rsgi_wsrpc.core...` and `rsgi_wsrpc.plugins...`.
"""
import sys
import importlib
from importlib.abc import MetaPathFinder, Loader
from importlib.machinery import ModuleSpec


class _AliasLoader(Loader):
    """
    Transparent loader that returns the already imported canonical module
    without re-executing its bytecode, preventing duplicate class/table definitions.
    """
    def __init__(self, target_module):
        self.target_module = target_module

    def create_module(self, spec):
        return self.target_module

    def exec_module(self, module):
        pass


class _LegacyAliasFinder(MetaPathFinder):
    """
    Transparent meta path finder redirecting legacy root imports:
    - `core` -> `rsgi_wsrpc.core`
    - `core.<submodule>` -> `rsgi_wsrpc.core.<submodule>`
    - `plugins` -> `rsgi_wsrpc.plugins`
    - `plugins.<submodule>` -> `rsgi_wsrpc.plugins.<submodule>`
    """

    MAPPING = {
        "core": "rsgi_wsrpc.core",
        "plugins": "rsgi_wsrpc.plugins",
    }

    def find_spec(self, fullname, path, target=None):
        if fullname in self.MAPPING:
            target_name = self.MAPPING[fullname]
        elif fullname.startswith("core."):
            target_name = "rsgi_wsrpc.core." + fullname[5:]
        elif fullname.startswith("plugins."):
            target_name = "rsgi_wsrpc.plugins." + fullname[8:]
        else:
            return None

        # 1. Если модуль уже загружен под целевым или исходным именем
        mod = sys.modules.get(target_name) or sys.modules.get(fullname)
        if mod is not None:
            sys.modules[fullname] = mod
            loader = _AliasLoader(mod)
            spec = ModuleSpec(fullname, loader, origin=getattr(mod, "__file__", None))
            spec.submodule_search_locations = getattr(mod, "__path__", None)
            return spec

        # 2. Иначе импортируем целевой канонический модуль
        try:
            mod = importlib.import_module(target_name)
            sys.modules[fullname] = mod
            loader = _AliasLoader(mod)
            spec = ModuleSpec(fullname, loader, origin=getattr(mod, "__file__", None))
            spec.submodule_search_locations = getattr(mod, "__path__", None)
            return spec
        except Exception:
            return None


def sync_legacy_aliases():
    """Синхронизирует все существующие подмодули rsgi_wsrpc.* в core.* и plugins.*."""
    for name, mod in list(sys.modules.items()):
        if name.startswith("rsgi_wsrpc.core"):
            alias = "core" + name[len("rsgi_wsrpc.core"):]
            sys.modules.setdefault(alias, mod)
        elif name.startswith("rsgi_wsrpc.plugins"):
            alias = "plugins" + name[len("rsgi_wsrpc.plugins"):]
            sys.modules.setdefault(alias, mod)


def install_compat():
    """
    Installs the backward-compatibility hook into sys.meta_path
    and sets up base aliases in sys.modules.
    """
    for finder in sys.meta_path:
        if isinstance(finder, _LegacyAliasFinder):
            return
    sys.meta_path.insert(0, _LegacyAliasFinder())

    try:
        import rsgi_wsrpc.core
        sys.modules.setdefault("core", rsgi_wsrpc.core)
    except Exception:
        pass

    try:
        import rsgi_wsrpc.plugins
        sys.modules.setdefault("plugins", rsgi_wsrpc.plugins)
    except Exception:
        pass

    sync_legacy_aliases()
