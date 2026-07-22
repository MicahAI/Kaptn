"""Tests for kaptn_defaults_set MCP tool."""

import json

from bridge.mcp import _state
from bridge.mcp.tools.tool_defaults_set import kaptn_defaults_set


class TestKaptnDefaultsSet:

    def test_set_approval_delay(self, setup_mcp_test_env):
        result = kaptn_defaults_set(approval_delay_seconds=3.0)
        assert result["status"] == "updated"
        assert any("3.0" in c for c in result["changes"])
        # Verify persisted to file
        cfg = _state._config_manager.load()
        assert cfg["poll_intervals"]["approvals"] == 3.0

    def test_set_approval_delay_too_low(self, setup_mcp_test_env):
        result = kaptn_defaults_set(approval_delay_seconds=0.1)
        assert "error" in result

    def test_set_reset_on_manual(self, setup_mcp_test_env):
        result = kaptn_defaults_set(reset_on_manual_approve=False)
        assert result["status"] == "updated"
        cfg = _state._config_manager.load()
        assert cfg["autopilot"]["reset_on_manual_approve"] is False

    def test_set_loop_threshold(self, setup_mcp_test_env):
        result = kaptn_defaults_set(loop_same_action_threshold=5)
        assert result["status"] == "updated"
        cfg = _state._config_manager.load()
        assert cfg["autopilot"]["loop_detection"]["same_action_threshold"] == 5

    def test_set_loop_threshold_too_low(self, setup_mcp_test_env):
        result = kaptn_defaults_set(loop_same_action_threshold=1)
        assert "error" in result

    def test_set_rule_action(self, setup_mcp_test_env):
        result = kaptn_defaults_set(rule_id="allow-unsafe", action="escalate")
        assert result["status"] == "updated"
        cfg = _state._config_manager.load()
        rule = next(r for r in cfg["autopilot"]["rules"] if r["id"] == "allow-unsafe")
        assert rule["action"] == "escalate"

    def test_set_rule_action_invalid(self, setup_mcp_test_env):
        result = kaptn_defaults_set(rule_id="allow-unsafe", action="explode")
        assert "error" in result

    def test_set_rule_not_found(self, setup_mcp_test_env):
        result = kaptn_defaults_set(rule_id="nonexistent", action="approve")
        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_set_rule_max_per_session(self, setup_mcp_test_env):
        result = kaptn_defaults_set(rule_id="allow-unsafe", max_per_session=50)
        assert result["status"] == "updated"
        cfg = _state._config_manager.load()
        rule = next(r for r in cfg["autopilot"]["rules"] if r["id"] == "allow-unsafe")
        assert rule["limits"]["max_per_session"] == 50

    def test_remove_limit_with_zero(self, setup_mcp_test_env):
        result = kaptn_defaults_set(rule_id="allow-unsafe", max_per_session=0)
        assert result["status"] == "updated"
        cfg = _state._config_manager.load()
        rule = next(r for r in cfg["autopilot"]["rules"] if r["id"] == "allow-unsafe")
        assert "max_per_session" not in rule.get("limits", {})

    def test_set_command_patterns(self, setup_mcp_test_env):
        result = kaptn_defaults_set(
            rule_id="allow-unsafe",
            command_patterns=["echo *", "sleep *", "ls *"],
        )
        assert result["status"] == "updated"
        cfg = _state._config_manager.load()
        rule = next(r for r in cfg["autopilot"]["rules"] if r["id"] == "allow-unsafe")
        assert rule["conditions"]["command_patterns"] == ["echo *", "sleep *", "ls *"]

    def test_remove_command_patterns(self, setup_mcp_test_env):
        kaptn_defaults_set(rule_id="allow-unsafe", command_patterns=["echo *"])
        result = kaptn_defaults_set(rule_id="allow-unsafe", command_patterns=[])
        assert result["status"] == "updated"
        cfg = _state._config_manager.load()
        rule = next(r for r in cfg["autopilot"]["rules"] if r["id"] == "allow-unsafe")
        assert "conditions" not in rule or "command_patterns" not in rule.get("conditions", {})

    def test_set_multiple_changes(self, setup_mcp_test_env):
        result = kaptn_defaults_set(
            approval_delay_seconds=2.0,
            reset_on_manual_approve=False,
        )
        assert result["status"] == "updated"
        assert len(result["changes"]) == 2

    def test_set_default_watch_minutes(self, setup_mcp_test_env):
        result = kaptn_defaults_set(default_watch_minutes=30)
        assert result["status"] == "updated"
        cfg = _state._config_manager.load()
        assert cfg["autopilot"]["default_watch_minutes"] == 30

    def test_set_default_watch_minutes_too_low(self, setup_mcp_test_env):
        result = kaptn_defaults_set(default_watch_minutes=0)
        assert "error" in result

    def test_set_default_watch_minutes_too_high(self, setup_mcp_test_env):
        result = kaptn_defaults_set(default_watch_minutes=500)
        assert "error" in result

    def test_set_no_changes(self, setup_mcp_test_env):
        result = kaptn_defaults_set()
        assert "error" in result

    def test_persists_to_config_file(self, setup_mcp_test_env):
        result = kaptn_defaults_set(approval_delay_seconds=5.0)
        assert result["persisted"] is True
        cfg = _state._config_manager.load()
        assert cfg["poll_intervals"]["approvals"] == 5.0

    def test_not_initialized(self, setup_mcp_test_env):
        _state._config_manager = None
        result = kaptn_defaults_set(approval_delay_seconds=3.0)
        assert "error" in result
