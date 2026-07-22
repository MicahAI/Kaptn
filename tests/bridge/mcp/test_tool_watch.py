"""Tests for kaptn_watch MCP tool."""

from bridge.mcp import _progress
from bridge.mcp.tools.tool_watch import kaptn_watch


class TestKaptnWatch:

    def test_watch_default_categories(self, setup_mcp_test_env):
        result = kaptn_watch(window="Kaptn", minutes=10)
        assert result["status"] == "watching"
        assert result["window"] == "Kaptn"
        assert result["minutes"] == 10
        # Verify command was written
        cmds = _progress.read_commands()
        rules = cmds["temp_rules"]
        assert any(r["action"] == "create_watch" and r["window"] == "Kaptn" for r in rules)

    def test_watch_custom_categories(self, setup_mcp_test_env):
        result = kaptn_watch(window="Kaptn", minutes=5, categories=["command_safe", "file_read"])
        assert result["status"] == "watching"
        assert result["categories"] == ["command_safe", "file_read"]
        cmds = _progress.read_commands()
        watch_cmd = next(r for r in cmds["temp_rules"] if r["action"] == "create_watch")
        assert watch_cmd["categories"] == ["command_safe", "file_read"]

    def test_watch_also_sends_resume(self, setup_mcp_test_env):
        result = kaptn_watch(window="Kaptn", minutes=10)
        assert result["status"] == "watching"
        cmds = _progress.read_commands()
        actions = [r["action"] for r in cmds["temp_rules"]]
        assert "resume_window" in actions

    def test_watch_invalid_minutes(self, setup_mcp_test_env):
        result = kaptn_watch(window="Kaptn", minutes=0)
        assert "error" in result
        result = kaptn_watch(window="Kaptn", minutes=999)
        assert "error" in result

    def test_watch_uses_config_default_when_no_minutes(self, setup_mcp_test_env):
        """When minutes not provided, uses autopilot.default_watch_minutes from config."""
        # Set default in config
        cfg = setup_mcp_test_env["config_manager"].load()
        cfg.setdefault("autopilot", {})["default_watch_minutes"] = 30
        setup_mcp_test_env["config_manager"].save(cfg)

        result = kaptn_watch(window="Kaptn")
        assert result["status"] == "watching"
        assert result["minutes"] == 30

    def test_watch_uses_fallback_when_no_config_default(self, setup_mcp_test_env):
        """When neither minutes arg nor config default, uses _FALLBACK_WATCH_MINUTES (20)."""
        result = kaptn_watch(window="Kaptn")
        assert result["status"] == "watching"
        assert result["minutes"] == 20

    def test_watch_explicit_minutes_overrides_config(self, setup_mcp_test_env):
        """Explicit minutes arg takes precedence over config default."""
        cfg = setup_mcp_test_env["config_manager"].load()
        cfg.setdefault("autopilot", {})["default_watch_minutes"] = 30
        setup_mcp_test_env["config_manager"].save(cfg)

        result = kaptn_watch(window="Kaptn", minutes=5)
        assert result["minutes"] == 5

    def test_watch_not_running(self, setup_mcp_test_env):
        _progress.clear_progress()
        result = kaptn_watch(window="Kaptn", minutes=10)
        assert "error" in result
        assert "Bridge not running" in result["error"]
