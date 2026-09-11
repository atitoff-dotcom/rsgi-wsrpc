# -*- coding: utf-8 -*-
"""
Тест-сьют: Аутентификация и проверка ролей (Auth Suite).
"""

from tests.framework import (
    PersonaManager,
    TestClient,
    assert_rpc_success,
    assert_rpc_error,
)


async def test_guest_public_access():
    """Проверяет доступ гостя к публичным методам."""
    async with await PersonaManager.as_guest() as client:
        # system.echo доступен всем
        res = await client.call("system.echo", {"msg": "hello"})
        assert_rpc_success(res, expected_keys=["status", "echo"])
        assert res["echo"]["msg"] == "hello"

        # auth.get_menu_items возвращает публичное меню
        menu = await client.call("auth.get_menu_items", {})
        assert isinstance(menu, list)


async def test_login_invalid_password():
    """Проверяет отклонение входа с неверным паролем."""
    async with await PersonaManager.as_guest() as client:
        await assert_rpc_error(
            client.call("login.submit", {
                "username": "non_existent_or_bad_user",
                "password": "WrongPassword123!",
            }),
            expected_message="Неверный логин или пароль",
        )


async def test_login_and_whoami():
    """Проверяет успешный вход администратора и метод login.whoami."""
    async with await PersonaManager.as_admin() as client:
        whoami = await client.call("login.whoami", {})
        assert_rpc_success(whoami, expected_keys=["user_id", "username", "roles"])
        assert "admin" in whoami["roles"] or whoami.get("is_superadmin") is True


async def test_token_refresh():
    """Проверяет продление сессии через токен обновления (login.refresh)."""
    async with await PersonaManager.as_admin() as client:
        refresh_token = client.token
        assert refresh_token is not None, "У авторизованного клиента должен быть refresh-токен"

        # Открываем новое соединение и продлеваем сессию
        async with await PersonaManager.as_guest() as guest_client:
            res = await guest_client.call("login.refresh", {"token": refresh_token})
            assert_rpc_success(res, expected_keys=["token", "jwt_token"])
            assert res["token"] is not None
