"""Tests for kaptn_connect MCP tool."""

import os
from io import StringIO
from unittest.mock import patch, MagicMock

from bridge.mcp import _progress, _state
from bridge.mcp.tools.tool_connect import kaptn_connect
from tests.bridge.mcp.conftest import fake_bridge_progress


def _mock_open_log():
    """Patch builtins.open in tool_connect to return a StringIO instead of a real file."""
    return patch("bridge.mcp.tools.tool_connect.open", return_value=StringIO())


class TestKaptnConnect:

    def test_connect_already_running(self, setup_mcp_test_env):
        """If bridge is already running, return current status."""
        fake_bridge_progress(windows=["Kaptn"])
        result = kaptn_connect(config=setup_mcp_test_env["config_path"])
        assert result["status"] == "already_running"
        assert result["windows"] == ["Kaptn"]

    def test_connect_already_running_with_error(self, setup_mcp_test_env):
        fake_bridge_progress(error="CDP not available")
        result = kaptn_connect(config=setup_mcp_test_env["config_path"])
        assert result["status"] == "already_running"
        assert result["error"] == "CDP not available"

    def test_connect_spawns_subprocess(self, setup_mcp_test_env):
        """When not running, should spawn a subprocess."""
        _progress.clear_progress()
        mock_proc = MagicMock()
        mock_proc.pid = 42
        with _mock_open_log(), patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            result = kaptn_connect(config=setup_mcp_test_env["config_path"])
        assert result["status"] == "started"
        assert result["pid"] == 42
        assert result["log_file"] == _progress.WORKER_LOG_FILE
        mock_popen.assert_called_once()
        # Verify progress file was written
        progress = _progress.read_progress()
        assert progress["pid"] == 42
        assert progress["running"] is True

    def test_connect_missing_config(self, setup_mcp_test_env):
        _progress.clear_progress()
        result = kaptn_connect(config="/nonexistent/config.json")
        assert "error" in result
        assert "not found" in result["error"]

    def test_connect_uses_state_config_path(self, setup_mcp_test_env):
        """Falls back to _state._config_path when no config arg given."""
        _progress.clear_progress()
        mock_proc = MagicMock()
        mock_proc.pid = 99
        with _mock_open_log(), patch("subprocess.Popen", return_value=mock_proc):
            result = kaptn_connect()
        assert result["status"] == "started"

    def test_connect_popen_failure(self, setup_mcp_test_env):
        _progress.clear_progress()
        with _mock_open_log(), patch("subprocess.Popen", side_effect=OSError("Permission denied")):
            result = kaptn_connect(config=setup_mcp_test_env["config_path"])
        assert "error" in result
        assert "Permission denied" in result["error"]
