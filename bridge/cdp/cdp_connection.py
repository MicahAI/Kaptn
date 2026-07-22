"""CDP WebSocket connection — persistent connection to an IDE debug target."""

import asyncio
import json
import logging

import websockets
from websockets.asyncio.client import ClientConnection

logger = logging.getLogger(__name__)


class CdpConnection:
    """Manages a WebSocket connection to a CDP debug target.

    Handles connecting, sending commands, receiving responses,
    and auto-reconnecting on disconnect.
    """

    def __init__(self, websocket_url: str, reconnect_delay: float = 2.0) -> None:
        """Initialize a CDP connection.

        Args:
            websocket_url: The WebSocket URL of the CDP target.
            reconnect_delay: Seconds to wait before reconnecting after disconnect.
        """
        self.websocket_url = websocket_url
        self.reconnect_delay = reconnect_delay
        self._ws: ClientConnection | None = None
        self._message_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._connected = False
        self._receive_task: asyncio.Task | None = None

    @property
    def connected(self) -> bool:
        """Whether the connection is currently active."""
        return self._connected

    async def connect(self) -> None:
        """Establish WebSocket connection to the CDP target.

        Raises:
            ConnectionError: If the connection cannot be established.
        """
        logger.info("Connecting to CDP target: %s", self.websocket_url)
        try:
            self._ws = await websockets.connect(self.websocket_url, max_size=10 * 1024 * 1024)
            self._connected = True
            self._receive_task = asyncio.create_task(self._receive_loop())
            logger.info("CDP connection established")
        except Exception as e:
            logger.error("Failed to connect to CDP: %s", e)
            raise ConnectionError(f"Failed to connect to CDP: {e}") from e

    async def disconnect(self) -> None:
        """Close the WebSocket connection."""
        self._connected = False
        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
            self._receive_task = None
        if self._ws:
            await self._ws.close()
            self._ws = None
        # Resolve any pending futures with errors
        for future in self._pending.values():
            if not future.done():
                future.set_exception(ConnectionError("CDP connection closed"))
        self._pending.clear()
        logger.info("CDP connection closed")

    async def send(self, method: str, params: dict | None = None, timeout: float = 10.0) -> dict:
        """Send a CDP command and wait for its response.

        Args:
            method: CDP method name (e.g., 'Runtime.evaluate').
            params: Optional parameters for the method.
            timeout: Seconds to wait for a response.

        Returns:
            The CDP response result dict.

        Raises:
            ConnectionError: If not connected.
            TimeoutError: If the response doesn't arrive within timeout.
        """
        if not self._connected or not self._ws:
            raise ConnectionError("Not connected to CDP")

        self._message_id += 1
        msg_id = self._message_id

        message = {"id": msg_id, "method": method}
        if params:
            message["params"] = params

        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[msg_id] = future

        logger.debug("CDP send: id=%d method=%s", msg_id, method)
        await self._ws.send(json.dumps(message))

        try:
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            self._pending.pop(msg_id, None)
            logger.error("CDP timeout waiting for response to id=%d method=%s", msg_id, method)
            raise TimeoutError(f"CDP response timeout for {method}") from None

    async def _receive_loop(self) -> None:
        """Background task that reads CDP WebSocket messages and resolves pending futures."""
        try:
            async for raw_message in self._ws:
                try:
                    message = json.loads(raw_message)
                except json.JSONDecodeError:
                    logger.warning("Received non-JSON CDP message")
                    continue

                msg_id = message.get("id")
                if msg_id is not None and msg_id in self._pending:
                    future = self._pending.pop(msg_id)
                    if "error" in message:
                        future.set_exception(
                            RuntimeError(f"CDP error: {message['error'].get('message', 'unknown')}")
                        )
                    elif not future.done():
                        future.set_result(message.get("result", {}))
                # Events (no id) are ignored for now — will be used by monitors later

        except websockets.exceptions.ConnectionClosed:
            logger.warning("CDP WebSocket connection closed")
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("Unexpected error in CDP receive loop")
        finally:
            self._connected = False
            logger.info("CDP receive loop ended")
