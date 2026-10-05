# -*- coding: utf-8 -*-
"""
rsgi_wsrpc.plugins.crud.auth: Аутентификация и управление сессиями для панели CRUD.
Обеспечивает изоляцию административной панели от неавторизованных пользователей и гостей.
"""

from __future__ import annotations
import inspect
import secrets
from typing import Dict, Any, Optional, Callable

# Реестр активных сессий администраторов CRUD: token -> {username, role, ...}
_ACTIVE_CRUD_SESSIONS: Dict[str, Dict[str, Any]] = {}

# Пользовательский верификатор учетных данных: fn(username, password) -> Optional[dict]
_crud_authenticator: Optional[Callable[[str, str], Any]] = None


def set_crud_authenticator(func: Callable[[str, str], Any]) -> None:
    """Устанавливает функцию валидации учетных данных администратора (username, password)."""
    global _crud_authenticator
    _crud_authenticator = func


def get_crud_authenticator() -> Optional[Callable[[str, str], Any]]:
    return _crud_authenticator


def create_crud_session(user_info: Dict[str, Any]) -> str:
    """Создает защищенный токен сессии администратора и регистрирует его."""
    token = secrets.token_hex(24)
    _ACTIVE_CRUD_SESSIONS[token] = user_info
    return token


def get_crud_session(token: str) -> Optional[Dict[str, Any]]:
    """Возвращает информацию о сессии по токену."""
    if not token:
        return None
    return _ACTIVE_CRUD_SESSIONS.get(token)


def revoke_crud_session(token: str) -> None:
    """Завершает сессию администратора."""
    if token:
        _ACTIVE_CRUD_SESSIONS.pop(token, None)


async def authenticate_admin(username: str, password: str) -> Optional[Dict[str, Any]]:
    """Проверяет учетные данные через зарегистрированный аутентификатор."""
    if not _crud_authenticator:
        return None
    try:
        if inspect.iscoroutinefunction(_crud_authenticator):
            res = await _crud_authenticator(username, password)
        else:
            res = _crud_authenticator(username, password)
        return res if res else None
    except Exception:
        return None


def render_login_html(error_message: Optional[str] = None, base_path: str = "/crud") -> str:
    """
    Генерирует стильный, адаптивный интерфейс авторизации администратора
    в единой дизайн-системе (светлая/темная тема, Tailwind-совместимый вид).
    """
    clean_base = base_path.rstrip("/")
    login_action = f"{clean_base}/login"

    error_html = ""
    if error_message:
        error_html = f"""
        <div style="background: rgba(225, 29, 72, 0.12); border: 1px solid rgba(225, 29, 72, 0.3); color: #f43f5e; padding: 10px 14px; border-radius: 8px; font-size: 13px; margin-bottom: 16px;">
          ⚠️ {error_message}
        </div>
        """

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Вход в панель управления | RSGI Admin</title>
  <style>
    :root {{
      --bg: #090d16;
      --card-bg: #111827;
      --border: #1f2937;
      --text: #f9fafb;
      --text-muted: #9ca3af;
      --primary: #3b82f6;
      --primary-hover: #2563eb;
      --input-bg: #0f172a;
      --input-border: #334155;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      background: var(--bg);
      color: var(--text);
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 16px;
    }}
    .login-card {{
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 32px;
      width: 100%;
      max-width: 420px;
      box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.5), 0 8px 10px -6px rgba(0, 0, 0, 0.5);
    }}
    .logo {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 44px;
      height: 44px;
      border-radius: 12px;
      background: var(--primary);
      color: #fff;
      font-size: 22px;
      font-weight: bold;
      margin-bottom: 16px;
    }}
    h1 {{
      font-size: 20px;
      font-weight: 700;
      margin-bottom: 6px;
    }}
    p.sub {{
      font-size: 13px;
      color: var(--text-muted);
      margin-bottom: 24px;
    }}
    .form-group {{
      margin-bottom: 16px;
    }}
    label {{
      display: block;
      font-size: 12px;
      font-weight: 600;
      margin-bottom: 6px;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }}
    input[type="text"], input[type="password"] {{
      width: 100%;
      padding: 10px 14px;
      border-radius: 8px;
      border: 1px solid var(--input-border);
      background: var(--input-bg);
      color: var(--text);
      font-size: 14px;
      outline: none;
      transition: border-color 0.2s;
    }}
    input:focus {{
      border-color: var(--primary);
      box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.2);
    }}
    .btn-submit {{
      width: 100%;
      padding: 12px;
      border-radius: 8px;
      border: none;
      background: var(--primary);
      color: #fff;
      font-size: 14px;
      font-weight: 600;
      cursor: pointer;
      margin-top: 8px;
      transition: background-color 0.2s;
    }}
    .btn-submit:hover {{
      background: var(--primary-hover);
    }}
    .demo-hint {{
      margin-top: 20px;
      padding: 12px;
      border-radius: 8px;
      background: rgba(255, 255, 255, 0.03);
      border: 1px dashed #374151;
      font-size: 12px;
      color: var(--text-muted);
      text-align: center;
    }}
    .demo-hint code {{
      color: #60a5fa;
      font-family: monospace;
      font-size: 13px;
    }}
    .quick-fill {{
      display: inline-block;
      margin-top: 6px;
      background: none;
      border: none;
      color: #60a5fa;
      text-decoration: underline;
      font-size: 12px;
      cursor: pointer;
    }}
    .back-link {{
      display: block;
      margin-top: 18px;
      text-align: center;
      font-size: 12px;
      color: var(--text-muted);
      text-decoration: none;
    }}
    .back-link:hover {{
      color: var(--text);
    }}
  </style>
</head>
<body>
  <div class="login-card">
    <div class="logo">⚡</div>
    <h1>Вход в RSGI Admin</h1>
    <p class="sub">Доступ к панели управления моделями разрешен только администраторам.</p>

    {error_html}

    <form method="POST" action="{login_action}">
      <div class="form-group">
        <label for="username">Логин</label>
        <input type="text" id="username" name="username" required autocomplete="username" placeholder="admin" autofocus>
      </div>

      <div class="form-group">
        <label for="password">Пароль</label>
        <input type="password" id="password" name="password" required autocomplete="current-password" placeholder="••••••••">
      </div>

      <button type="submit" class="btn-submit">Войти как администратор</button>
    </form>

    <div class="demo-hint">
      Для демонстрации используйте: <code>admin</code> / <code>admin123</code><br>
      <button type="button" class="quick-fill" onclick="document.getElementById('username').value='admin'; document.getElementById('password').value='admin123';">
        ⚡ Заполнить данные демо-админа
      </button>
    </div>

    <a href="/" class="back-link">← Вернуться на главную витрину</a>
  </div>
</body>
</html>"""
