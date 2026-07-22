"""Message logger — captures USER and CASCADE messages to a readable log file.

Writes to ~/.kaptn/logs/messages.log in a format that mirrors a real
Cascade session, with timing info for each message.

Format:
    [2026-03-08 21:15:13.748] [Kaptn] USER: What is the status?
    [2026-03-08 21:15:18.006] [Kaptn] CASCADE: The bridge is running with 2 windows...
"""

import logging
import os
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_KAPTN_LOGS_DIR = os.path.join(Path.home(), ".kaptn", "logs")
_DEFAULT_LOG_PATH = os.path.join(_KAPTN_LOGS_DIR, "messages.log")

# Only these roles get written to the messages log
_LOGGED_ROLES = {"user", "assistant", "thinking"}

# Map internal role names to display names
_ROLE_DISPLAY = {
    "user": "USER",
    "assistant": "CASCADE",
    "thinking": "THINKING",
}


class MessageLogger:
    """Appends USER/CASCADE messages to a plain-text log file with timestamps.

    Each message is one logical line:
        [timestamp] [window] ROLE: message text

    Multi-line message text is joined with spaces so each log entry
    stays on a single line for easy grep/tail.

    Args:
        log_path: Path to the messages log file. Defaults to ~/.kaptn/logs/messages.log.
    """

    def __init__(self, log_path: str = _DEFAULT_LOG_PATH) -> None:
        self.log_path = log_path
        self._file = None
        self._ensure_dir()

    def _ensure_dir(self) -> None:
        """Create the log directory if it doesn't exist."""
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)

    def _open(self):
        """Lazily open the log file for appending."""
        if self._file is None or self._file.closed:
            self._file = open(self.log_path, "a", encoding="utf-8")
        return self._file

    def log_message(self, window: str, role: str, text: str, timestamp: datetime | None = None) -> None:
        """Write a single message to the log file.

        Args:
            window: Window name (e.g. "Kaptn", "TelemetryMCPV2").
            role: Message role — only "user" and "assistant" are logged.
            text: Raw message text from the IDE.
            timestamp: Message timestamp. Defaults to now.
        """
        if role not in _LOGGED_ROLES:
            return

        ts = timestamp or datetime.now()
        ts_str = ts.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]  # millisecond precision
        display_role = _ROLE_DISPLAY.get(role, role.upper())

        # Collapse multi-line text to single line for log readability
        clean_text = " ".join(text.split())

        line = f"[{ts_str}] [{window}] {display_role}: {clean_text}\n"

        try:
            f = self._open()
            f.write(line)
            f.flush()
        except OSError:
            logger.exception("Failed to write to messages log: %s", self.log_path)

    def log_session_marker(self, window: str) -> None:
        """Write a session separator when a new conversation is detected.

        Args:
            window: Window name.
        """
        ts_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        line = f"\n--- [{ts_str}] [{window}] New conversation ---\n\n"
        try:
            f = self._open()
            f.write(line)
            f.flush()
        except OSError:
            logger.exception("Failed to write session marker to messages log")

    def close(self) -> None:
        """Close the log file."""
        if self._file and not self._file.closed:
            self._file.close()
            self._file = None
