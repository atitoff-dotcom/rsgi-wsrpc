# -*- coding: utf-8 -*-
"""
Тест-сьют: Сырые и бинарные WebSocket-сессии (plugins/raw_ws).
Проверяет уникальность 64-битных ID, диспетчеризацию по URL, явную передачу session_id,
двунаправленный обмен байтами и гарантированный перехват дисконнекта.
"""

import sys
import os
import unittest

# Добавляем корень rsgi-wsrpc в sys.path при прямом запуске
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from plugins.raw_ws import (
    generate_session_id,
    raw_ws_route,
    dispatch_raw_ws,
    get_session,
    send_to_session,
    broadcast_raw,
    ACTIVE_RAW_SESSIONS,
    RawWebSocketSession,
)


class MockCloseMessage:
    """Имитирует WebsocketInboundCloseMessage из Granian."""
    pass


class MockWebsocketMessage:
    def __init__(self, data):
        self.data = data


class MockRSGIWebSocket:
    """Мок сокетного протокола Granian."""
    def __init__(self, inbound_messages):
        self.inbound_messages = list(inbound_messages)
        self.sent_bytes = []
        self.sent_str = []
        self.closed = False
        self.close_code = None

    async def receive(self):
        if self.inbound_messages:
            return self.inbound_messages.pop(0)
        return MockCloseMessage()

    async def send_bytes(self, data: bytes):
        self.sent_bytes.append(data)

    async def send_str(self, data: str):
        self.sent_str.append(data)

    async def close(self, code: int = 1000):
        self.closed = True
        self.close_code = code


class MockRSGIProto:
    def __init__(self, ws):
        self._ws = ws
        self.accepted = False

    async def accept(self):
        self.accepted = True
        return self._ws


class TestRawWSSuite(unittest.IsolatedAsyncioTestCase):
    async def test_session_id_generation(self):
        """Проверяет генерацию 64-битных уникальных session_id."""
        count = 10_000
        ids = {generate_session_id() for _ in range(count)}
        self.assertEqual(len(ids), count, f"Обнаружены коллизии session_id! Ожидалось {count}, получено {len(ids)}")

        first_id = next(iter(ids))
        self.assertIsInstance(first_id, int, f"session_id должен быть целым числом, получено {type(first_id)}")
        self.assertGreater(first_id, 0, "session_id должен быть положительным числом")
        self.assertLessEqual(first_id.bit_length(), 64, "session_id превышает 64 бита")

    async def test_raw_ws_routing_and_explicit_session_id(self):
        """Проверяет маршрутизацию по URL и явную передачу session_id в обработчик."""
        received_packets = []
        connected_sessions = []
        disconnected_sessions = []

        @raw_ws_route("/ws/test_telemetry")
        async def on_telemetry(session_id: int, data: bytes, session: RawWebSocketSession):
            received_packets.append((session_id, data))
            self.assertIsInstance(session_id, int)
            self.assertEqual(session.session_id, session_id)
            # Ответ клиенту байтами
            await session.send_bytes(b"PONG:" + data)

        @on_telemetry.on_connect
        async def on_conn(session: RawWebSocketSession):
            connected_sessions.append(session.session_id)

        @on_telemetry.on_disconnect
        async def on_disc(session: RawWebSocketSession):
            disconnected_sessions.append(session.session_id)

        # Имитируем входящие пакеты и последующий дисконнект
        mock_ws = MockRSGIWebSocket([
            MockWebsocketMessage(b"PING_1"),
            MockWebsocketMessage(b"PING_2"),
            MockCloseMessage()
        ])
        proto = MockRSGIProto(mock_ws)
        scope = {"proto": "websocket", "path": "/ws/test_telemetry"}

        # 1. Диспетчеризация
        handled = await dispatch_raw_ws(scope, proto)
        self.assertTrue(handled, "Роут /ws/test_telemetry должен быть перехвачен")
        self.assertTrue(proto.accepted, "Соединение должно быть принято через accept()")

        # 2. Проверка полученных сообщений
        self.assertEqual(len(received_packets), 2)
        sid1, data1 = received_packets[0]
        self.assertEqual(data1, b"PING_1")
        self.assertEqual(mock_ws.sent_bytes, [b"PONG:PING_1", b"PONG:PING_2"])

        # 3. Проверка жизненного цикла (on_connect / on_disconnect)
        self.assertEqual(len(connected_sessions), 1)
        self.assertEqual(connected_sessions[0], sid1)
        self.assertEqual(len(disconnected_sessions), 1)
        self.assertEqual(disconnected_sessions[0], sid1)

        # 4. Проверка автоматической очистки реестра
        self.assertNotIn(sid1, ACTIVE_RAW_SESSIONS, "Сессия должна быть удалена из реестра после завершения")

    async def test_raw_ws_unhandled_route(self):
        """Проверяет, что незарегистрированные пути не перехватываются."""
        mock_ws = MockRSGIWebSocket([])
        proto = MockRSGIProto(mock_ws)
        scope = {"proto": "websocket", "path": "/ws/standard_wsrpc"}

        handled = await dispatch_raw_ws(scope, proto)
        self.assertFalse(handled, "Стандартный путь не должен перехватываться плагином raw_ws")
        self.assertFalse(proto.accepted)

    async def test_send_to_session_and_broadcast(self):
        """Проверяет отправку сообщения по session_id и широковещательную рассылку."""
        mock_ws1 = MockRSGIWebSocket([])
        mock_ws2 = MockRSGIWebSocket([])

        session1 = RawWebSocketSession(mock_ws1, 1001, {"path": "/ws/channel_a"})
        session2 = RawWebSocketSession(mock_ws2, 1002, {"path": "/ws/channel_b"})

        ACTIVE_RAW_SESSIONS[1001] = session1
        ACTIVE_RAW_SESSIONS[1002] = session2

        try:
            # Проверка get_session
            self.assertIs(get_session(1001), session1)
            self.assertIsNone(get_session(9999))

            # Проверка адресной отправки по session_id
            res = await send_to_session(1001, b"DIRECT_MESSAGE")
            self.assertTrue(res)
            self.assertEqual(mock_ws1.sent_bytes, [b"DIRECT_MESSAGE"])
            self.assertEqual(len(mock_ws2.sent_bytes), 0)

            # Проверка broadcast_raw по всем каналам
            sent_count = await broadcast_raw(b"BROADCAST_ALL")
            self.assertEqual(sent_count, 2)
            self.assertIn(b"BROADCAST_ALL", mock_ws1.sent_bytes)
            self.assertIn(b"BROADCAST_ALL", mock_ws2.sent_bytes)

            # Проверка broadcast_raw с фильтрацией по path
            sent_count_a = await broadcast_raw(b"BROADCAST_A_ONLY", path="/ws/channel_a")
            self.assertEqual(sent_count_a, 1)
            self.assertIn(b"BROADCAST_A_ONLY", mock_ws1.sent_bytes)
            self.assertNotIn(b"BROADCAST_A_ONLY", mock_ws2.sent_bytes)

        finally:
            ACTIVE_RAW_SESSIONS.pop(1001, None)
            ACTIVE_RAW_SESSIONS.pop(1002, None)


# Для совместимости с tests/run.py, где ищутся функции test_*
async def test_session_id_generation():
    test_case = TestRawWSSuite()
    await test_case.test_session_id_generation()

async def test_raw_ws_routing_and_explicit_session_id():
    test_case = TestRawWSSuite()
    await test_case.test_raw_ws_routing_and_explicit_session_id()

async def test_raw_ws_unhandled_route():
    test_case = TestRawWSSuite()
    await test_case.test_raw_ws_unhandled_route()

async def test_send_to_session_and_broadcast():
    test_case = TestRawWSSuite()
    await test_case.test_send_to_session_and_broadcast()


if __name__ == "__main__":
    unittest.main()
