"""Tests for CdpConnection — WebSocket connection to CDP targets."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from bridge.cdp.cdp_connection import CdpConnection


class TestCdpConnection:
    """Tests for the CdpConnection class."""

    def test_init(self):
        """Connection initializes with correct defaults."""
        conn = CdpConnection("ws://localhost:9222/devtools/page/ABC")
        assert conn.websocket_url == "ws://localhost:9222/devtools/page/ABC"
        assert conn.reconnect_delay == 2.0
        assert conn.connected is False

    def test_init_custom_reconnect_delay(self):
        """Custom reconnect delay is respected."""
        conn = CdpConnection("ws://localhost:9222/devtools/page/ABC", reconnect_delay=5.0)
        assert conn.reconnect_delay == 5.0

    @pytest.mark.asyncio
    async def test_send_raises_when_not_connected(self):
        """send() raises ConnectionError when not connected."""
        conn = CdpConnection("ws://localhost:9222/devtools/page/ABC")
        with pytest.raises(ConnectionError, match="Not connected"):
            await conn.send("Runtime.evaluate")

    @pytest.mark.asyncio
    async def test_disconnect_resolves_pending_futures(self):
        """disconnect() resolves pending futures with ConnectionError."""
        conn = CdpConnection("ws://localhost:9222/devtools/page/ABC")
        conn._connected = True
        conn._ws = AsyncMock()

        future = asyncio.get_event_loop().create_future()
        conn._pending[1] = future

        await conn.disconnect()

        assert conn.connected is False
        assert len(conn._pending) == 0
        with pytest.raises(ConnectionError):
            future.result()

    @pytest.mark.asyncio
    async def test_disconnect_when_already_disconnected(self):
        """disconnect() is safe to call when already disconnected."""
        conn = CdpConnection("ws://localhost:9222/devtools/page/ABC")
        await conn.disconnect()  # Should not raise
        assert conn.connected is False
