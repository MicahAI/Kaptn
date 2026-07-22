"""Shared fixtures for MCP tool handler tests.

With the subprocess architecture, most tools communicate via JSON files:
    progress.json — bridge → MCP (status, windows, errors)
    commands.json — MCP → bridge (temp rules, config changes)

Tests simulate a running bridge by writing fake progress files and
verify tools write correct commands. No actual subprocess is spawned.
"""

import json
import os

import pytest

from bridge.config.config_manager import ConfigManager
from bridge.mcp import _state
from bridge.mcp import _progress


# --- Test config data ---

TEST_RULES = [
    {"id": "allow-safe", "category": "command_safe", "action": "approve", "limits": {"max_per_session": 100}},
    {"id": "allow-unsafe", "category": "command_unsafe", "action": "approve", "limits": {"max_per_session": 20}},
    {"id": "block-deletes", "category": "file_delete", "action": "deny"},
]

TEST_CONFIG = {
    "poll_intervals": {"approvals": 1.0, "messages": 2.0, "status": 5.0},
    "autopilot": {
        "enabled": True,
        "reset_on_manual_approve": True,
        "rules": TEST_RULES,
        "loop_detection": {"same_action_threshold": 3, "oscillation_threshold": 3, "history_size": 20},
    },
}


def fake_bridge_progress(*, running=True, windows=None, error=None, pid=None):
    """Write a fake bridge progress file simulating a running bridge."""
    import time
    data = {
        "running": running,
        "pid": pid or os.getpid(),  # Use current PID so is_bridge_running() returns True
        "cdp_port": 9222,
        "timestamp": time.time(),
        "windows": windows or ["Kaptn", "TelemetryMCPV2"],
    }
    if error:
        data["error"] = error
    _progress.write_progress(data)
    return data


@pytest.fixture(autouse=True)
def setup_mcp_test_env(tmp_path):
    """Set up isolated test environment with temp files and config.

    - Redirects progress/commands files to a temp dir
    - Creates a temp config file with test config
    - Initializes _state with a real ConfigManager
    - Cleans up after each test
    """
    # Redirect all kaptn files to temp dir
    kaptn_dir = str(tmp_path / "kaptn")
    logs_dir = os.path.join(kaptn_dir, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    orig_dir = _progress._KAPTN_DIR
    orig_logs_dir = _progress.LOGS_DIR
    orig_progress = _progress.PROGRESS_FILE
    orig_commands = _progress.COMMANDS_FILE
    orig_worker_log = _progress.WORKER_LOG_FILE
    _progress._KAPTN_DIR = kaptn_dir
    _progress.LOGS_DIR = logs_dir
    _progress.PROGRESS_FILE = os.path.join(kaptn_dir, "bridge_progress.json")
    _progress.COMMANDS_FILE = os.path.join(kaptn_dir, "bridge_commands.json")
    _progress.WORKER_LOG_FILE = os.path.join(logs_dir, "bridge_worker.log")

    # Create temp config file
    config_path = str(tmp_path / "kaptn.config.json")
    with open(config_path, "w") as f:
        json.dump(TEST_CONFIG, f)

    # Initialize _state
    config_manager = ConfigManager(config_path)
    _state._config_manager = config_manager
    _state._config_path = config_path
    _state._temp_rules = None
    _state._bridge = None

    # Write fake progress so tools think bridge is running
    fake_bridge_progress()

    yield {
        "config_path": config_path,
        "config_manager": config_manager,
        "kaptn_dir": kaptn_dir,
    }

    # Clean up
    _progress._KAPTN_DIR = orig_dir
    _progress.LOGS_DIR = orig_logs_dir
    _progress.PROGRESS_FILE = orig_progress
    _progress.COMMANDS_FILE = orig_commands
    _progress.WORKER_LOG_FILE = orig_worker_log
    _state._config_manager = None
    _state._config_path = None
    _state._temp_rules = None
    _state._bridge = None
