"""Tests for kaptn_defaults MCP tool."""

from bridge.mcp import _state
from bridge.mcp.tools.tool_defaults import kaptn_defaults


class TestKaptnDefaults:

    def test_defaults_shows_rules(self, setup_mcp_test_env):
        result = kaptn_defaults()
        assert "rules" in result
        assert len(result["rules"]) == 3
        ids = [r["id"] for r in result["rules"]]
        assert "allow-safe" in ids
        assert "allow-unsafe" in ids
        assert "block-deletes" in ids

    def test_defaults_shows_poll_intervals(self, setup_mcp_test_env):
        result = kaptn_defaults()
        assert result["poll_intervals"]["approvals_seconds"] == 1.0
        assert result["poll_intervals"]["messages_seconds"] == 2.0
        assert result["poll_intervals"]["status_seconds"] == 5.0

    def test_defaults_shows_settings(self, setup_mcp_test_env):
        result = kaptn_defaults()
        assert result["autopilot_enabled"] is True
        assert result["default_watch_minutes"] == 20  # fallback default
        assert result["reset_on_manual_approve"] is True
        assert result["loop_detection"]["same_action_threshold"] == 3

    def test_defaults_shows_rule_limits(self, setup_mcp_test_env):
        result = kaptn_defaults()
        safe_rule = next(r for r in result["rules"] if r["id"] == "allow-safe")
        assert safe_rule["limits"]["max_per_session"] == 100
        unsafe_rule = next(r for r in result["rules"] if r["id"] == "allow-unsafe")
        assert unsafe_rule["limits"]["max_per_session"] == 20

    def test_defaults_shows_config_file(self, setup_mcp_test_env):
        result = kaptn_defaults()
        assert "kaptn.config.json" in result["config_file"]

    def test_defaults_not_initialized(self, setup_mcp_test_env):
        _state._config_manager = None
        result = kaptn_defaults()
        assert "error" in result
