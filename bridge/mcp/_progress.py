"""Atomic JSON file helpers for bridge ↔ MCP server communication.

Two files:
    progress.json — bridge → MCP (status, errors, windows)
    commands.json — MCP → bridge (temp rules, config changes)

Both use atomic writes (mkstemp + os.replace) to prevent partial reads.
"""

import json
import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# Fixed location: ~/.kaptn/ (predictable, survives reboots, easy to find)
_KAPTN_DIR = os.path.join(Path.home(), ".kaptn")
LOGS_DIR = os.path.join(_KAPTN_DIR, "logs")
PROGRESS_FILE = os.path.join(_KAPTN_DIR, "bridge_progress.json")
COMMANDS_FILE = os.path.join(_KAPTN_DIR, "bridge_commands.json")
WORKER_LOG_FILE = os.path.join(LOGS_DIR, "bridge_worker.log")


def _ensure_dir() -> None:
    """Create ~/.kaptn/ and ~/.kaptn/logs/ if they don't exist."""
    os.makedirs(LOGS_DIR, exist_ok=True)


def write_atomic(path: str, data: dict) -> None:
    """Write JSON data atomically using temp file + os.replace.

    Args:
        path: Target file path.
        data: Dict to serialize as JSON.
    """
    _ensure_dir()
    dir_path = os.path.dirname(path)
    try:
        tmp_fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
        with os.fdopen(tmp_fd, "w") as f:
            json.dump(data, f)
        os.replace(tmp_path, path)
    except OSError:
        logger.exception("Failed to write %s", path)
        # Clean up temp file if replace failed
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def read_json(path: str) -> dict:
    """Read JSON file, returning empty dict on any error.

    Args:
        path: File path to read.

    Returns:
        Parsed dict, or empty dict if file missing/corrupt.
    """
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def read_progress() -> dict:
    """Read bridge progress/status.

    Returns:
        Dict with keys like: running, pid, windows, error, cdp_port.
    """
    return read_json(PROGRESS_FILE)


def write_progress(data: dict) -> None:
    """Write bridge progress/status atomically."""
    write_atomic(PROGRESS_FILE, data)


def read_commands() -> dict:
    """Read pending commands from MCP server.

    Returns:
        Dict with keys like: temp_rules, config_changes.
    """
    return read_json(COMMANDS_FILE)


def write_commands(data: dict) -> None:
    """Write commands for bridge to pick up atomically."""
    write_atomic(COMMANDS_FILE, data)


def clear_commands() -> None:
    """Remove the commands file after bridge has processed it."""
    try:
        os.unlink(COMMANDS_FILE)
    except OSError:
        pass


def clear_progress() -> None:
    """Remove the progress file (e.g., on clean shutdown)."""
    try:
        os.unlink(PROGRESS_FILE)
    except OSError:
        pass


def is_bridge_running() -> bool:
    """Check if a bridge subprocess is currently running.

    Reads progress file and validates the PID is still alive.

    Returns:
        True if bridge process is running.
    """
    progress = read_progress()
    if not progress.get("running"):
        return False

    pid = progress.get("pid")
    if not pid:
        return False

    # Check if process is actually alive
    try:
        os.kill(pid, 0)  # signal 0 = check existence, don't kill
        return True
    except (OSError, ProcessLookupError):
        # Stale progress file — process died
        logger.warning("Bridge PID %d no longer running, clearing stale progress", pid)
        clear_progress()
        return False
