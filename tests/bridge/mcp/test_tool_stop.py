"""Tests for kaptn_stop MCP tool."""

from bridge.mcp import _progress
from bridge.mcp.tools.tool_stop import kaptn_stop
from tests.bridge.mcp.conftest import fake_bridge_progress


class TestKaptnStop:

    def test_stop_by_rule_id(self, setup_mcp_test_env):
        result = kaptn_stop(rule_id="tmp-123")
        assert result["status"] == "stopping"
        cmds = _progress.read_commands()
        assert any(r["action"] == "stop_rule" and r["rule_id"] == "tmp-123" for r in cmds["temp_rules"])

    def test_stop_by_window(self, setup_mcp_test_env):
        result = kaptn_stop(window="Kaptn")
        assert result["status"] == "stopping"
        cmds = _progress.read_commands()
        assert any(r["action"] == "stop_window" and r["window"] == "Kaptn" for r in cmds["temp_rules"])

    def test_stop_all(self, setup_mcp_test_env):
        result = kaptn_stop(all=True)
        assert result["status"] == "stopping"
        cmds = _progress.read_commands()
        assert any(r["action"] == "stop_all" for r in cmds["temp_rules"])

    def test_stop_no_args_returns_error(self, setup_mcp_test_env):
        result = kaptn_stop()
        assert "error" in result

    def test_stop_not_running(self, setup_mcp_test_env):
        _progress.clear_progress()
        result = kaptn_stop(window="Kaptn")
        assert "error" in result

    def test_disconnect_when_not_running(self, setup_mcp_test_env):
        _progress.clear_progress()
        result = kaptn_stop(disconnect=True)
        assert result["status"] == "not_running"

    def test_disconnect_kills_bridge(self, setup_mcp_test_env):
        # Use current PID so is_bridge_running returns True but we mock the kill
        from unittest.mock import patch
        fake_bridge_progress(pid=99999)
        with patch("os.kill") as mock_kill:
            mock_kill.side_effect = ProcessLookupError
            result = kaptn_stop(disconnect=True)
        assert result["status"] == "not_running"
