"""Tests for kaptn_approve_category MCP tool."""

from bridge.mcp import _progress
from bridge.mcp.tools.tool_approve_category import kaptn_approve_category


class TestKaptnApproveCategory:

    def test_approve_valid_category(self, setup_mcp_test_env):
        result = kaptn_approve_category(category="command_unsafe", minutes=10)
        assert result["status"] == "active"
        assert result["category"] == "command_unsafe"
        cmds = _progress.read_commands()
        assert any(r["action"] == "create_rule" and r["category"] == "command_unsafe" for r in cmds["temp_rules"])

    def test_approve_with_max_count(self, setup_mcp_test_env):
        result = kaptn_approve_category(category="command_safe", minutes=5, max_count=3)
        assert result["status"] == "active"
        assert result["max_count"] == 3

    def test_approve_with_window(self, setup_mcp_test_env):
        result = kaptn_approve_category(category="file_write", minutes=10, window="Kaptn")
        assert result["status"] == "active"
        assert result["window"] == "Kaptn"

    def test_approve_invalid_category(self, setup_mcp_test_env):
        result = kaptn_approve_category(category="invalid", minutes=10)
        assert "error" in result

    def test_approve_not_running(self, setup_mcp_test_env):
        _progress.clear_progress()
        result = kaptn_approve_category(category="command_safe", minutes=10)
        assert "error" in result
