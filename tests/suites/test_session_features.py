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
