import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from rsgi_wsrpc.core.session import JsonRpcSession, rpc_method, RPC_REGISTRY, RPCError
from rsgi_wsrpc.core.constants import UserRole

class MockWs:
    def __init__(self, incoming_messages=None):
        self.sent = []
        self.incoming = list(incoming_messages or [])

    async def receive(self):
        if not self.incoming:
            # Emulate close message
            msg = MagicMock()
            msg.__class__.__name__ = "WebsocketInboundCloseMessage"
            return msg
        item = self.incoming.pop(0)
        msg = MagicMock()
        msg.__class__.__name__ = "WebsocketInboundTextMessage"
        msg.data = item
        return msg

    def send_str(self, text):
        self.sent.append(text)
        fut = asyncio.get_running_loop().create_future()
        fut.set_result(None)
        return fut


@pytest.mark.asyncio
async def test_session_rejects_non_dict_json():
    ws = MockWs([b"[1, 2, 3]"])
    session = JsonRpcSession(ws, session_id=1)
    await session.start()
    
    assert len(ws.sent) == 1
    assert "Invalid Request: root must be a JSON object" in ws.sent[0]
    assert "-32600" in ws.sent[0]


@pytest.mark.asyncio
async def test_session_message_size_limit():
    large_payload = b'{"jsonrpc": "2.0", "method": "test", "params": "' + (b'x' * (11 * 1024 * 1024)) + b'"}'
    ws = MockWs([large_payload])
    session = JsonRpcSession(ws, session_id=2)
    await session.start()

    assert len(ws.sent) == 1
    assert "Message too large" in ws.sent[0]


@pytest.mark.asyncio
async def test_session_send_request_cleanup_on_timeout():
    ws = MockWs([])
    session = JsonRpcSession(ws, session_id=3)
    session.data = MagicMock()  # Mark authenticated

    with pytest.raises(asyncio.TimeoutError):
        await session.send_request("client.test", timeout=0.01)

    # Future must be removed from pending requests on timeout
    assert len(session._pending_requests) == 0


@pytest.mark.asyncio
async def test_session_multi_roles_access():
    @rpc_method("editor.only", role=UserRole.ADMIN)
    async def editor_action(session, params):
        return {"status": "ok"}

    # Case 1: Session has UserRole.ADMIN in user_roles
    class MockAuthSession:
        user_role = UserRole.GUEST
        user_roles = [UserRole.GUEST, UserRole.ADMIN]

    handler = RPC_REGISTRY["editor.only"]
    res = await handler(MockAuthSession(), {})
    assert res == {"status": "ok"}

    # Case 2: Session has only GUEST
    class MockGuestSession:
        user_role = UserRole.GUEST
        user_roles = [UserRole.GUEST]

    with pytest.raises(RPCError) as exc:
        await handler(MockGuestSession(), {})
    assert exc.value.code == -32003


@pytest.mark.asyncio
async def test_rpc_method_with_invalidates_and_wrappers():
    from rsgi_wsrpc.plugins.smart_cache import invalidates

    called = {}

    @rpc_method("test.delete_topic")
    @invalidates(tags=["forum.topics", "forum.topic.{topic_id|id}"])
    async def delete_topic(session, params):
        called["session"] = session
        called["params"] = params
        return {"deleted": True}

    handler = RPC_REGISTRY["test.delete_topic"]
    mock_session = MagicMock()
    res = await handler(mock_session, {"topic_id": 42})
    assert res == {"deleted": True}
    assert called["session"] is mock_session
    assert called["params"] == {"topic_id": 42}

    # Test generic wrapper without @wraps
    def dummy_decorator_no_wraps(func):
        async def generic_wrapper(*args, **kwargs):
            return await func(*args, **kwargs)
        return generic_wrapper

    called_generic = {}

    @rpc_method("test.generic_wrapped")
    @dummy_decorator_no_wraps
    async def generic_handler(session, params):
        called_generic["session"] = session
        called_generic["params"] = params
        return {"ok": True}

    handler_generic = RPC_REGISTRY["test.generic_wrapped"]
    res_generic = await handler_generic(mock_session, {"foo": "bar"})
    assert res_generic == {"ok": True}
    assert called_generic["session"] is mock_session
    assert called_generic["params"] == {"foo": "bar"}

    # Test invalidates with kwargs mapping
    called_kwargs = {}

    @rpc_method("test.kwargs_wrapped")
    @invalidates(tags=["forum.topic.{topic_id}"])
    async def kwargs_handler(topic_id: int):
        called_kwargs["topic_id"] = topic_id
        return {"id": topic_id}

    handler_kwargs = RPC_REGISTRY["test.kwargs_wrapped"]
    res_kwargs = await handler_kwargs(mock_session, {"topic_id": 99})
    assert res_kwargs == {"id": 99}
    assert called_kwargs["topic_id"] == 99

