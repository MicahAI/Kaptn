"""Logging configuration for the Kaptn bridge.

Provides structured JSON logging for machine parsing and
human-readable console output for development.
"""

import logging
import json
import sys
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    """Formats log records as JSON lines for machine parsing."""

    def format(self, record: logging.LogRecord) -> str:
        """Format a log record as a JSON string."""
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = self.formatException(record.exc_info)
        if hasattr(record, "window"):
            log_entry["window"] = record.window
        if hasattr(record, "rule_id"):
            log_entry["rule_id"] = record.rule_id
        return json.dumps(log_entry)


class ConsoleFormatter(logging.Formatter):
    """Human-readable colored console output for development."""

    COLORS = {
        "DEBUG": "\033[36m",     # Cyan
        "INFO": "\033[32m",      # Green
        "WARNING": "\033[33m",   # Yellow
        "ERROR": "\033[31m",     # Red
        "CRITICAL": "\033[35m",  # Magenta
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        """Format a log record with color for console output."""
        color = self.COLORS.get(record.levelname, self.RESET)
        timestamp = datetime.now().strftime("%H:%M:%S")
        prefix = f"{color}[{record.levelname:>8}]{self.RESET} {timestamp}"

        window = getattr(record, "window", None)
        if window:
            prefix += f" [{window}]"

        return f"{prefix} {record.getMessage()}"


def setup_logging(
    level: str = "INFO",
    log_format: str = "console",
    log_file: str | None = None,
    per_module: dict[str, str] | None = None,
) -> None:
    """Configure logging for the Kaptn bridge.

    Args:
        level: Default log level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        log_format: Output format — 'console' for human-readable, 'json' for structured.
        log_file: Optional file path for log output. None means stdout only.
        per_module: Optional dict of module name → log level overrides.
    """
    root_logger = logging.getLogger("bridge")
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Clear existing handlers
    root_logger.handlers.clear()

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    if log_format == "json":
        console_handler.setFormatter(JsonFormatter())
    else:
        console_handler.setFormatter(ConsoleFormatter())
    root_logger.addHandler(console_handler)

    # File handler (always JSON for machine parsing)
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(JsonFormatter())
        root_logger.addHandler(file_handler)

    # Per-module overrides
    if per_module:
        for module_name, module_level in per_module.items():
            module_logger = logging.getLogger(module_name)
            module_logger.setLevel(getattr(logging, module_level.upper(), logging.INFO))
