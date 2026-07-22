"""Tests for kaptn_status MCP tool."""

from bridge.mcp import _progress
from bridge.mcp.tools.tool_status import kaptn_status
from tests.bridge.mcp.conftest import fake_bridge_progress


class TestKaptnStatus:

    def test_status_shows_windows(self, setup_mcp_test_env):
        result = kaptn_status()
        assert result["bridge"] == "running"
        assert "Kaptn" in result["windows"]
        assert "TelemetryMCPV2" in result["windows"]

    def test_status_filter_window(self, setup_mcp_test_env):
        result = kaptn_status(window="Kaptn")
        assert result["windows"] == ["Kaptn"]

    def test_status_shows_error(self, setup_mcp_test_env):
        fake_bridge_progress(error="CDP not available on port 9222")
        result = kaptn_status()
        assert result["error"] == "CDP not available on port 9222"

    def test_status_not_running(self, setup_mcp_test_env):
        _progress.clear_progress()
        result = kaptn_status()
        assert result["bridge"] == "not_running"
        assert "kaptn_connect" in result["message"]

    def test_status_shows_temp_rules(self, setup_mcp_test_env):
        import time
        _progress.write_progress({
            "running": True,
            "pid": __import__("os").getpid(),
            "cdp_port": 9222,
            "timestamp": time.time(),
            "windows": ["Kaptn"],
            "temp_rules": [
                {"category": "command_safe", "window": "Kaptn", "minutes": 10},
            ],
        })
        result = kaptn_status(window="Kaptn")
        assert result["temp_rule_count"] == 1

    def test_status_stale_warning(self, setup_mcp_test_env):
        import time
        _progress.write_progress({
            "running": True,
            "pid": __import__("os").getpid(),
            "cdp_port": 9222,
            "timestamp": time.time() - 30,
            "windows": [],
        })
        result = kaptn_status()
        assert "warning" in result
