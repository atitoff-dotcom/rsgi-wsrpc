# core/constants.py
from enum import Enum

WS_CLOSE_CODES = {
    1000: "Normal Closure (Штатный выход)",
    1001: "Going Away (Вкладка закрыта или страница обновлена)",
    1002: "Protocol Error (Ошибка протокола вебсокета)",
    1003: "Unsupported Data (Получен неподдерживаемый тип данных)",
    1005: "No Status Rcvd (Ожидался код закрытия, но ничего не пришло)",
    1006: "Abnormal Closure (Аварийный обрыв: обрыв сети, таймаут heartbeat)",
    1007: "Invalid frame payload data (Некорректные данные внутри фрейма)",
    1008: "Policy Violation (Нарушение политики безопасности)",
    1009: "Message Too Big (Клиент прислал слишком большой пакет)",
    1011: "Internal Error (Критическая ошибка на стороне сервера)",
}

# Системные роли безопасности
ADMIN_ROLE = "admin"
DEFAULT_USER_ROLE = "user"
SYSTEM_ROLES = frozenset({ADMIN_ROLE, DEFAULT_USER_ROLE})
