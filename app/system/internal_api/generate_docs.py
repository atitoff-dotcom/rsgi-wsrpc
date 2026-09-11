# -*- coding: utf-8 -*-

import os
import sys
import ast
import inspect
import textwrap
from typing import Dict, Any

# Добавляем корень проекта в sys.path для корректных импортов
# Путь изменен на 3 уровня вверх, так как файл теперь находится в app/system/internal_api/
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from core.session import rpc_method, RPC_REGISTRY, RPCError
from core.constants import UserRole
from app.session import Session

def extract_closure_vars(wrapper) -> Dict[str, Any]:
    """
    Извлекает переменные замыкания из функции-обертки RPC.
    """
    closure_dict = {}
    if hasattr(wrapper, "__closure__") and wrapper.__closure__:
        for var_name, cell in zip(wrapper.__code__.co_freevars, wrapper.__closure__):
            closure_dict[var_name] = cell.cell_contents
    return closure_dict

def clean_docstring(docstring: str) -> str:
    """
    Очищает docstring согласно PEP 257.
    """
    if not docstring:
        return "Без описания"
    return inspect.cleandoc(docstring).strip()

def split_docstring(docstring: str):
    """
    Разделяет docstring на основное описание и детали (Args/Returns).
    """
    idx = -1
    for term in ["Args:", "Returns:", "args:", "returns:"]:
        pos = docstring.find(term)
        if pos != -1:
            if idx == -1 or pos < idx:
                idx = pos
                
    if idx != -1:
        main_desc = docstring[:idx].strip()
        details = docstring[idx:].strip()
        return main_desc, details
    else:
        return docstring, ""

def extract_args_from_func(func) -> Dict[str, Any]:
    """
    Анализирует AST исходного кода функции для извлечения аргументов,
    получаемых через args.get('name', default_val) или args['name'].
    """
    try:
        source = inspect.getsource(func)
        # Убираем общую начальную индентацию, так как метод может быть внутри класса
        dedented_source = textwrap.dedent(source)
        tree = ast.parse(dedented_source)
    except Exception:
        return {}

    params = {}
    for node in ast.walk(tree):
        # 1. Проверяем вызовы args.get('key', default)
        if (isinstance(node, ast.Call) and 
            isinstance(node.func, ast.Attribute) and 
            isinstance(node.func.value, ast.Name) and 
            node.func.value.id == 'args' and 
            node.func.attr == 'get'):
            
            if len(node.args) >= 1:
                key_node = node.args[0]
                if isinstance(key_node, ast.Constant):
                    key = key_node.value
                elif isinstance(key_node, ast.Str):
                    key = key_node.s
                else:
                    continue
                
                default_val = None
                if len(node.args) >= 2:
                    default_node = node.args[1]
                    try:
                        default_val = ast.literal_eval(default_node)
                    except ValueError:
                        default_val = "..."
                
                params[key] = default_val

        # 2. Проверяем получение через args['key']
        elif (isinstance(node, ast.Subscript) and
              isinstance(node.value, ast.Name) and
              node.value.id == 'args'):
            
            slice_node = node.slice
            # Поддержка разных версий Python (в 3.9+ slice_node содержит Constant напрямую, в старых - Index(value=Constant))
            key = None
            if isinstance(slice_node, ast.Constant):
                key = slice_node.value
            elif isinstance(slice_node, ast.Str):
                key = slice_node.s
            elif hasattr(ast, "Index") and isinstance(slice_node, ast.Index):
                index_val = slice_node.value
                if isinstance(index_val, ast.Constant):
                    key = index_val.value
                elif isinstance(index_val, ast.Str):
                    key = index_val.s

            if key and key not in params:
                params[key] = "..."
                
    return params

async def generate_http_api_docs():
    """
    Собирает все зарегистрированные RPC-методы с http=True и генерирует
    для них markdown документацию, а также сохраняет JSON метаданные в базу данных.
    """
    sorted_methods = sorted(RPC_REGISTRY.items(), key=lambda x: x[0])
    
    http_methods = []
    for name, wrapper in sorted_methods:
        if not getattr(wrapper, "http", False):
            continue
            
        closure = extract_closure_vars(wrapper)
        func = closure.get("func")
        role = closure.get("role")
        
        if not func:
            continue
            
        docstring = clean_docstring(func.__doc__)
        short_desc = docstring.splitlines()[0] if docstring else "Без описания"
        
        # Определяем роль
        if role is not None:
            role_str = role.value if hasattr(role, "value") else str(role)
        else:
            role_str = "guest" if name.startswith("login.") else "authenticated user"
            
        anchor = name.replace('.', '').lower()
        
        http_methods.append({
            "name": name,
            "wrapper": wrapper,
            "func": func,
            "role_str": role_str,
            "docstring": docstring,
            "short_desc": short_desc,
            "anchor": anchor
        })

    # --- ГЕНЕРАЦИЯ MARKDOWN ---
    md_content = []
    md_content.append("# Документация HTTP-RPC (Internal API)")
    md_content.append("")
    md_content.append("Этот файл сгенерирован автоматически на основе зарегистрированных обработчиков RPC с флагом `http=True`.")
    md_content.append("HTTP-RPC методы вызываются по пути `/api/...`, заменяя точки в названии метода на слэши `/`.")
    md_content.append("Например: метод `bank.list` доступен по пути `/api/bank/list`.")
    md_content.append("")
    md_content.append("## Список методов")
    md_content.append("")
    md_content.append("| Метод | Путь | Требуемая роль | Описание |")
    md_content.append("| :--- | :--- | :--- | :--- |")
    
    for item in http_methods:
        name = item["name"]
        path_str = f"`/api/{name.replace('.', '/')}`"
        md_content.append(f"| [{name}](#{item['anchor']}) | {path_str} | `{item['role_str']}` | {item['short_desc']} |")
        
    md_content.append("")
    md_content.append("---")
    md_content.append("")
    md_content.append("## Детальное описание методов")
    md_content.append("")
    
    # Группируем методы по префиксу
    grouped_methods = {}
    for item in http_methods:
        name = item["name"]
        prefix = name.split(".")[0] if "." in name else "other"
        grouped_methods.setdefault(prefix, []).append(item)
        
    for prefix in sorted(grouped_methods.keys()):
        md_content.append(f"## Раздел {prefix}")
        md_content.append("")
        
        for item in grouped_methods[prefix]:
            name = item["name"]
            func = item["func"]
            role_str = item["role_str"]
            docstring = item["docstring"]
            anchor = item["anchor"]
            
            filepath = func.__code__.co_filename
            lineno = func.__code__.co_firstlineno
            try:
                rel_path = os.path.relpath(filepath, root_dir)
                rel_path = rel_path.replace(os.sep, '/')
            except Exception:
                rel_path = filepath
                
            file_link = f"[{rel_path}:{lineno}](../../{rel_path}#L{lineno})"
            main_desc, details = split_docstring(docstring)
            
            md_content.append(f'<a id="{anchor}"></a>')
            md_content.append(f"### {name}")
            md_content.append("")
            md_content.append(f"**HTTP Путь:** `POST /api/{name.replace('.', '/')}`")
            md_content.append("")
            md_content.append(f"**Путь к файлу:** {file_link}")
            md_content.append("")
            md_content.append(f"**Требуемая роль:** `{role_str}`")
            md_content.append("")
            md_content.append(f"**Описание:** {main_desc}")
            md_content.append("")
            
            # Извлекаем параметры через AST
            params = extract_args_from_func(func)
            if params:
                md_content.append("**Параметры (JSON):**")
                md_content.append("```json")
                import json
                md_content.append(json.dumps(params, indent=2, ensure_ascii=False))
                md_content.append("```")
                md_content.append("")
            
            if details:
                md_content.append("<details>")
                md_content.append("<summary><b>Показать параметры и возвращаемое значение</b></summary>")
                md_content.append("")
                md_content.append("```text")
                md_content.append(details)
                md_content.append("```")
                md_content.append("</details>")
                md_content.append("")
                
            md_content.append("---")
            md_content.append("")

    # Сохраняем Markdown файл
    md_output_path = os.path.join(root_dir, "docs", "app", "internal_rpc_api.md")
    os.makedirs(os.path.dirname(md_output_path), exist_ok=True)
    with open(md_output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_content))

    # --- СОХРАНЕНИЕ МЕТАДАННЫХ В БД ---
    methods_json_data = []
    for item in http_methods:
        methods_json_data.append({
            "name": item["name"],
            "path": f"/api/{item['name'].replace('.', '/')}",
            "role": item["role_str"],
            "description": item["docstring"],
            "short_desc": item["short_desc"],
            "filepath": item["func"].__code__.co_filename,
            "lineno": item["func"].__code__.co_firstlineno,
            "params": extract_args_from_func(item["func"])
        })
    
    from app.system.db import async_session
    # Импорт обновлен в рамках реструктуризации: перенос auth в system/auth
    from app.system.auth.models import SystemData
    from sqlalchemy import select

    async with async_session() as db:
        stmt = select(SystemData).where(SystemData.key == "http_rpc_api_docs")
        res = await db.execute(stmt)
        sys_data = res.scalar_one_or_none()
        if sys_data:
            sys_data.value = methods_json_data
        else:
            sys_data = SystemData(key="http_rpc_api_docs", value=methods_json_data)
            db.add(sys_data)
        await db.commit()
    from core.logger import logger
    logger.info("Документация API успешно сохранена в базу данных system_data")


@rpc_method("internal_api.generate_docs", role=UserRole.ADMIN, http=True)
async def handle_generate_docs(session: Session, args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Генерирует файлы документации internal_rpc_api.md и сохраняет метаданные API в базу данных.
    """
    try:
        await generate_http_api_docs()
        return {"success": True, "message": "Документация в БД и Markdown успешно обновлена"}
    except Exception as e:
        from core.logger import logger
        logger.error(f"Ошибка при генерации документации: {str(e)}", exc_info=True)
        raise RPCError(f"Ошибка при генерации документации: {str(e)}")
