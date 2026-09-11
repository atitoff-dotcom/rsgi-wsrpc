import logging
import traceback
import orjson
from typing import Any

from app.config import settings
from core.session import RPC_REGISTRY, RPCError, current_transport_ctx, current_session_ctx
from core.constants import UserRole
from app.session import Session as AppSession

# Импортируем генератор документации для регистрации его RPC-метода (путь обновлен в рамках реструктуризации)
from app.system.internal_api.generate_docs import handle_generate_docs

logger = logging.getLogger("app.internal_api")

class MockTransportSession:
    """
    Класс-заглушка для имитации транспортной WebSocket сессии.
    Используется для корректного цветного логирования действий скрипта через core.logger.
    """
    def __init__(self, ip: str, data: Any):
        self.ip = ip
        self.data = data


async def handle_internal_api(scope, proto):
    """
    HTTP обработчик запросов для внутренних банковских скриптов.
    Сопоставляет пути вида POST /api/bank/list с RPC-методами (например, bank.list),
    если для этих методов включен флаг http=True.
    """
    # 0. Возвращаем интерактивную документацию (api.html) при GET-запросе к корню API
    if scope.method == "GET" and (scope.path == "/api" or scope.path == "/api/"):
        try:
            import os
            # Путь к api.html теперь определяется относительно текущего файла
            html_path = os.path.join(os.path.dirname(__file__), "api.html")
            if os.path.exists(html_path):
                with open(html_path, "r", encoding="utf-8") as f:
                    html_content = f.read()
                
                # Загружаем метаданные методов из БД (system_data)
                from app.system.db import async_session
                # Импорт обновлен в рамках реструктуризации
                from app.system.auth.models import SystemData
                from sqlalchemy import select
                import json
                
                methods_json_str = "[]"
                async with async_session() as db:
                    stmt = select(SystemData).where(SystemData.key == "http_rpc_api_docs")
                    res = await db.execute(stmt)
                    sys_data = res.scalar_one_or_none()
                    if sys_data and sys_data.value is not None:
                        methods_json_str = json.dumps(sys_data.value, ensure_ascii=False, indent=2)
                
                # Загружаем токен из настроек
                internal_api_cfg = getattr(settings, "internal_api", None)
                token = getattr(internal_api_cfg, "token", "default-banking-secret-token") if internal_api_cfg else "default-banking-secret-token"
                
                # Подставляем динамические данные в шаблон
                html_content = html_content.replace("{token}", token).replace("{methods_json_str}", methods_json_str)
                
                await proto.response_str(
                    status=200,
                    headers=[
                        ("content-type", "text/html; charset=utf-8"),
                        ("access-control-allow-origin", "*")
                    ],
                    body=html_content
                )
                return
            else:
                await proto.response_str(
                    status=404,
                    headers=[
                        ("content-type", "text/plain; charset=utf-8"),
                        ("access-control-allow-origin", "*")
                    ],
                    body="Документация не найдена. Пожалуйста, сгенерируйте её в панели администратора."
                )
                return
        except Exception as e:
            logger.error(f"Ошибка при отдаче api.html: {e}")
            await proto.response_str(
                status=500,
                headers=[
                    ("content-type", "text/plain; charset=utf-8"),
                    ("access-control-allow-origin", "*")
                ],
                body="Внутренняя ошибка сервера при загрузке документации."
            )
            return

    # 1. Проверяем токен авторизации
    auth_header = scope.headers.get("authorization") or scope.headers.get("Authorization")
    if auth_header and isinstance(auth_header, bytes):
        auth_header = auth_header.decode("utf-8")

    token = None
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]

    internal_api_cfg = getattr(settings, "internal_api", None)
    configured_token = internal_api_cfg.token if internal_api_cfg else None

    if not configured_token or token != configured_token:
        logger.warning(f"Попытка несанкционированного доступа к API. Токен не совпадает.")
        resp_data = orjson.dumps({"error": "Unauthorized"})
        proto.response_str(
            status=401,
            headers=[
                ("content-type", "application/json"),
                ("access-control-allow-origin", "*")
            ],
            body=resp_data.decode("utf-8")
        )
        return

    # 2. Определяем имя RPC метода на основе пути запроса
    path_stripped = scope.path.strip("/")
    if path_stripped.startswith("api"):
        method_subpath = path_stripped[len("api"):].strip("/")
    else:
        method_subpath = path_stripped

    method_name = method_subpath.replace("/", ".")

    # 3. Ищем обработчик в RPC_REGISTRY
    handler = RPC_REGISTRY.get(method_name)
    if not handler or not getattr(handler, "http", False):
        logger.warning(f"Запрошен неизвестный или закрытый для HTTP метод: '{method_name}'")
        resp_data = orjson.dumps({"error": f"Method '{method_name}' not found"})
        proto.response_str(
            status=404,
            headers=[
                ("content-type", "application/json"),
                ("access-control-allow-origin", "*")
            ],
            body=resp_data.decode("utf-8")
        )
        return

    # 4. Читаем тело HTTP запроса (параметры метода), если указан Content-Length > 0
    content_length_val = scope.headers.get("content-length") or scope.headers.get("Content-Length")
    if content_length_val and isinstance(content_length_val, bytes):
        content_length_val = content_length_val.decode("utf-8")

    content_length = 0
    if content_length_val:
        try:
            content_length = int(content_length_val)
        except ValueError:
            pass

    body = bytearray()
    if content_length > 0:
        try:
            # В RSGI чтение тела происходит путем асинхронного итерирования по протоколу
            async for chunk in proto:
                body.extend(chunk)
                if len(body) >= content_length:
                    break
        except Exception as e:
            logger.error(f"Ошибка при чтении тела запроса: {e}")
            resp_data = orjson.dumps({"error": "Failed to read request body"})
            proto.response_str(
                status=400,
                headers=[("content-type", "application/json")],
                body=resp_data.decode("utf-8")
            )
            return

    # Декодируем параметры запроса
    params = {}
    if body:
        try:
            params = orjson.loads(body)
            if not isinstance(params, dict):
                resp_data = orjson.dumps({"error": "Request body must be a JSON object"})
                proto.response_str(
                    status=400,
                    headers=[("content-type", "application/json")],
                    body=resp_data.decode("utf-8")
                )
                return
        except Exception:
            resp_data = orjson.dumps({"error": "Invalid JSON in request body"})
            proto.response_str(
                status=400,
                headers=[("content-type", "application/json")],
                body=resp_data.decode("utf-8")
            )
            return

    # 5. Создаем мок-сессии для вызова обработчика
    ip_address = "127.0.0.1"
    if getattr(scope, "client", None) and isinstance(scope.client, (list, tuple)) and len(scope.client) > 0:
        ip_address = scope.client[0]

    internal_session = AppSession(
        uid=0,
        user=None,
        user_name="internal_script",
        user_role=UserRole.ADMIN,
        user_roles=["admin"],
        session_db_id=0,
        user_ctx=None,
    )

    transport_mock = MockTransportSession(ip_address, internal_session)

    # Устанавливаем контекстные переменные для правильного логирования и прав доступа
    transport_token = current_transport_ctx.set(transport_mock)
    session_token = current_session_ctx.set(internal_session)

    try:
        # Вызываем RPC-хендлер
        result = await handler(internal_session, params)

        # Формируем успешный ответ
        resp_data = orjson.dumps(result)
        proto.response_str(
            status=200,
            headers=[
                ("content-type", "application/json"),
                ("access-control-allow-origin", "*")
            ],
            body=resp_data.decode("utf-8")
        )
    except RPCError as e:
        # Ошибки валидации бизнес-логики
        resp_data = orjson.dumps({"error": e.message})
        proto.response_str(
            status=400,
            headers=[
                ("content-type", "application/json"),
                ("access-control-allow-origin", "*")
            ],
            body=resp_data.decode("utf-8")
        )
    except Exception as e:
        # Непредвиденные системные ошибки
        logger.error(f"Критическая ошибка при вызове HTTP-RPC метода '{method_name}': {e}")
        traceback.print_exc()
        resp_data = orjson.dumps({"error": "Internal server error"})
        proto.response_str(
            status=500,
            headers=[("content-type", "application/json")],
            body=resp_data.decode("utf-8")
        )
    finally:
        current_transport_ctx.reset(transport_token)
        current_session_ctx.reset(session_token)
