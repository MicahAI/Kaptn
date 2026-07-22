"""Tests for kaptn_resume MCP tool."""

from bridge.mcp import _progress
from bridge.mcp.tools.tool_resume import kaptn_resume


class TestKaptnResume:

    def test_resume_window(self, setup_mcp_test_env):
        result = kaptn_resume(window="Kaptn")
        assert result["status"] == "resuming"
        cmds = _progress.read_commands()
        assert any(r["action"] == "resume_window" and r["window"] == "Kaptn" for r in cmds["temp_rules"])

    def test_resume_all(self, setup_mcp_test_env):
        result = kaptn_resume(all=True)
        assert result["status"] == "resuming"
        cmds = _progress.read_commands()
        assert any(r["action"] == "resume_all" for r in cmds["temp_rules"])

    def test_resume_no_args_returns_error(self, setup_mcp_test_env):
        result = kaptn_resume()
        assert "error" in result

    def test_resume_not_running(self, setup_mcp_test_env):
        _progress.clear_progress()
        result = kaptn_resume(window="Kaptn")
        assert "error" in result
        assert "Bridge not running" in result["error"]
