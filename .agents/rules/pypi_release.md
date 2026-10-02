# pypi_release

Правила публикации версий в PyPI:
1. **Единый источник версий**:
   - Версия пакета задается в `pyproject.toml` (`version = "x.y.z"`) и `rsgi_wsrpc/__init__.py` (`__version__ = "x.y.z"`).
2. **Перед публикацией**:
   - Запустить валидатор пакета: `python /home/alex/hydro_calc/utils/verify_rsgi_package.py`.
   - Убедиться, что в `dist/` нет namespace pollution (в wheel входят только `rsgi_wsrpc*`).
3. **Сборка и загрузка**:
   - Сборка: `python -m build --sdist --wheel`.
   - Загрузка: `python -m twine upload dist/rsgi_wsrpc-<version>*`.
   - Публикация версий выполняется только с явного подтверждения пользователя.
