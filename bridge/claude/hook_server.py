"""HTTP server that receives Claude Code hook events for the Kaptn bridge.

Listens on localhost only. The hook client (bridge.claude.hook_client)
POSTs each PreToolUse event to /hook and relays the decision back to
Claude Code.
"""

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from bridge.claude.claude_adapter import ClaudeAdapter

logger = logging.getLogger(__name__)

DEFAULT_HOOK_PORT = 3002


class _HookHandler(BaseHTTPRequestHandler):
    """Handles POST /hook (decisions) and GET /health (liveness)."""

    server: "_HookHTTPServer"

    def do_POST(self) -> None:  # noqa: N802 — http.server API
        """Evaluate a hook event and respond with the decision JSON."""
        if self.path == "/reset":
            self._send(200, self.server.adapter.reset())
            return
        if self.path != "/hook":
            self._send(404, {"error": "not found"})
            return

        try:
            length = int(self.headers.get("Content-Length", 0))
            event = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            self._send(400, {"error": "invalid json"})
            return

        try:
            result = self.server.adapter.handle_hook_event(event)
        except Exception:
            logger.exception("Hook evaluation failed")
            self._send(500, {"error": "internal error"})
            return

        self._send(200, result or {})

    def do_GET(self) -> None:  # noqa: N802 — http.server API
        """Health check and live-status endpoints."""
        if self.path == "/health":
            self._send(200, {"status": "ok"})
        elif self.path == "/status":
            self._send(200, self.server.adapter.status())
        else:
            self._send(404, {"error": "not found"})

    def _send(self, code: int, payload: dict) -> None:
        """Write a JSON response."""
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:  # noqa: A002 — http.server API
        """Route http.server access logs to the module logger at debug."""
        logger.debug("hook_server: " + format, *args)


class _HookHTTPServer(ThreadingHTTPServer):
    """ThreadingHTTPServer carrying the adapter reference."""

    daemon_threads = True
    adapter: ClaudeAdapter


class ClaudeHookServer:
    """Runs the hook HTTP server on a background thread."""

    def __init__(
        self,
        adapter: ClaudeAdapter,
        host: str = "127.0.0.1",
        port: int = DEFAULT_HOOK_PORT,
    ) -> None:
        """Initialize the server (does not bind until start()).

        Args:
            adapter: The ClaudeAdapter that evaluates events.
            host: Bind address — localhost only by default.
            port: TCP port. Use 0 to let the OS pick (tests).
        """
        self.adapter = adapter
        self.host = host
        self._requested_port = port
        self._httpd: _HookHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        """The actual bound port (resolves port=0), or the requested port."""
        if self._httpd:
            return self._httpd.server_address[1]
        return self._requested_port

    @property
    def running(self) -> bool:
        """Whether the server thread is active."""
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        """Bind the port and start serving on a daemon thread.

        Raises:
            OSError: If the port is already in use.
        """
        self._httpd = _HookHTTPServer((self.host, self._requested_port), _HookHandler)
        self._httpd.adapter = self.adapter
        self._thread = threading.Thread(
            target=self._httpd.serve_forever,
            name="kaptn-claude-hook-server",
            daemon=True,
        )
        self._thread.start()
        logger.info("Claude hook server listening on %s:%d", self.host, self.port)

    def stop(self) -> None:
        """Shut down the server and release the port."""
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("Claude hook server stopped")
