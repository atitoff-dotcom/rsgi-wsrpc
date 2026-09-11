# -*- coding: utf-8 -*-
"""
Утверждения (Assertions) для тестирования RPC-ответов и WebSocket событий.
"""

from typing import Any, Dict, List, Optional
from tests.framework.client import RPCClientError


def assert_rpc_success(result: Any, expected_keys: Optional[List[str]] = None) -> Any:
    """Проверяет успешность RPC-ответа и наличие обязательных ключей."""
    assert result is not None, "Результат RPC-запроса не должен быть None"
    if expected_keys and isinstance(result, dict):
        for key in expected_keys:
            assert key in result, f"Ключ '{key}' отсутствует в ответе сервера: {result}"
    return result


async def assert_rpc_error(coroutine, expected_code: Optional[int] = None, expected_message: Optional[str] = None):
    """
    Проверяет, что асинхронный вызов RPC приводит к ошибке с ожидаемым кодом/сообщением.
    """
    try:
        res = await coroutine
        raise AssertionError(f"Ожидалась ошибка RPCClientError, но вызов успешно вернул: {res}")
    except RPCClientError as err:
        if expected_code is not None:
            assert err.code == expected_code, f"Ожидался код ошибки {expected_code}, получен {err.code} ({err.message})"
        if expected_message is not None:
            assert expected_message.lower() in err.message.lower(), (
                f"Сообщение ошибки '{err.message}' не содержит подстроку '{expected_message}'"
            )
        return err


def assert_notification(
    notif: Dict[str, Any],
    expected_method: str,
    expected_params_subset: Optional[Dict[str, Any]] = None,
):
    """Проверяет структуру и параметры полученной push-нотификации."""
    assert notif.get("method") == expected_method, (
        f"Ожидался метод нотификации '{expected_method}', получен '{notif.get('method')}'"
    )
    params = notif.get("params", {})
    if expected_params_subset:
        for k, v in expected_params_subset.items():
            assert k in params, f"Параметр '{k}' отсутствует в нотификации: {params}"
            assert params[k] == v, f"Параметр '{k}' равен '{params[k]}', ожидался '{v}'"
