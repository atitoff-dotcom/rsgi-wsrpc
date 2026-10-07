import pytest
import os
import tempfile
import asyncio
from unittest.mock import MagicMock, AsyncMock

from rsgi_wsrpc.app import RsgiWsrpcApp
from rsgi_wsrpc.core.lib.config import settings


class MockScope:
    def __init__(self, proto="http", method="GET", path="/", client=("192.168.1.50", 12345), headers=None):
        self.proto = proto
        self.method = method
        self.path = path
        self.client = client
        self.headers = headers or []


class MockProto:
    def __init__(self):
        self.status = None
        self.headers = None
        self.body = None
        self.file_path = None
        self.accepted = False

    def response_str(self, status, headers, body):
        self.status = status
        self.headers = headers
        self.body = body

    def response_bytes(self, status, headers, body):
        self.status = status
        self.headers = headers
        self.body = body

    def response_file(self, status, headers, file):
        self.status = status
        self.headers = headers
        self.file_path = file

    async def accept(self):
        self.accepted = True
        ws = MagicMock()
        # Immediately return a close message on receive
        close_msg = MagicMock()
        close_msg.__class__.__name__ = "WebsocketInboundCloseMessage"
        ws.receive = AsyncMock(return_value=close_msg)
        ws.send_str = MagicMock()
        return ws


@pytest.mark.asyncio
async def test_app_config_initialization():
    from rsgi_wsrpc import VkOAuth, YandexOAuth

    app = RsgiWsrpcApp(
        secret_key="custom-app-secret",
        password_iterations=750000,
        login_rpc="custom_login.",
        db_echo=True,
        max_upload_size=50 * 1024 * 1024,
        oauth=[
            VkOAuth(client_id="vk-123", client_secret="vk-secret"),
            YandexOAuth(client_id="ya-456", client_secret="ya-secret"),
        ]
    )
    assert settings.security.get("secret_key") == "custom-app-secret"
    assert settings.security.get("password_iterations") == 750000
    assert settings.security.get("login_rpc") == "custom_login."
    assert settings.get("db_echo") is True
    assert settings.get("max_upload_size") == 50 * 1024 * 1024
    assert settings.get("oauth")["vk"]["client_id"] == "vk-123"
    assert settings.get("oauth")["yandex"]["client_id"] == "ya-456"


@pytest.mark.asyncio
async def test_app_cors_options():
    app = RsgiWsrpcApp(cors=True)
    scope = MockScope(proto="http", method="OPTIONS", path="/any")
    proto = MockProto()
    await app(scope, proto)

    assert proto.status == 204
    header_dict = dict(proto.headers)
    assert header_dict.get("access-control-allow-origin") == "*"
    assert "access-control-allow-methods" in header_dict


@pytest.mark.asyncio
async def test_app_static_file_serving_and_traversal_protection():
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Create a test file
        test_file = os.path.join(tmp_dir, "test.txt")
        with open(test_file, "w") as f:
            f.write("hello static world")

        # Secret file outside tmp_dir
        secret_dir = tempfile.mkdtemp()
        secret_file = os.path.join(secret_dir, "secret.txt")
        with open(secret_file, "w") as f:
            f.write("super-secret")

        app = RsgiWsrpcApp(static_dir=tmp_dir, static_prefix="/static")

        # 1. Valid static file with prefix
        scope = MockScope(proto="http", method="GET", path="/static/test.txt")
        proto = MockProto()
        await app(scope, proto)
        assert proto.status == 200
        assert proto.file_path == test_file

        # 2. Valid static file directly without prefix (e.g. /assets/...)
        scope = MockScope(proto="http", method="GET", path="/test.txt")
        proto = MockProto()
        await app(scope, proto)
        assert proto.status == 200
        assert proto.file_path == test_file

        # 3. Path traversal attack with prefix
        scope = MockScope(proto="http", method="GET", path="/static/../../" + os.path.basename(secret_dir) + "/secret.txt")
        proto = MockProto()
        await app(scope, proto)
        assert proto.status == 404

        # 4. Path traversal attack without prefix
        scope = MockScope(proto="http", method="GET", path="/../../" + os.path.basename(secret_dir) + "/secret.txt")
        proto = MockProto()
        await app(scope, proto)
        assert proto.status == 404


@pytest.mark.asyncio
async def test_app_websocket_accept():
    app = RsgiWsrpcApp()
    scope = MockScope(proto="websocket", client=("10.0.0.1", 54321))
    proto = MockProto()
    await app(scope, proto)
    assert proto.accepted is True


@pytest.mark.asyncio
async def test_app_seo_interceptor():
    from rsgi_wsrpc.plugins.seo import bot_page, SeoPageData

    @bot_page("/article/{id:int}")
    async def render_article(id: int):
        return SeoPageData(title=f"Article #{id}", description="SEO rendered")

    app = RsgiWsrpcApp(enable_seo=True)

    # 1. Запрос от Googlebot
    scope_bot = MockScope(
        proto="http",
        method="GET",
        path="/article/42",
        headers=[("user-agent", "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)")]
    )
    proto_bot = MockProto()
    await app(scope_bot, proto_bot)

    assert proto_bot.status == 200
    headers_bot = dict(proto_bot.headers)
    assert headers_bot.get("x-rendered-for") == "bot"
    assert "Article #42" in proto_bot.body

    # 2. Запрос от обычного браузера (должен пройти мимо SEO-перехватчика)
    scope_browser = MockScope(
        proto="http",
        method="GET",
        path="/article/42",
        headers=[("user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36")]
    )
    proto_browser = MockProto()
    await app(scope_browser, proto_browser)
    # Так как нет index_file или static, вернется 404 (перехватчик не сработал)
    assert proto_browser.status == 404
