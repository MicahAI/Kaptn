"""Tests for kaptn_audit MCP tool."""

from unittest.mock import patch, MagicMock

from bridge.mcp.tools.tool_audit import kaptn_audit


def _make_mock_audit(records):
    """Create a mock AuditLogger returning given records."""
    mock = MagicMock()
    mock.get_recent_by_time.return_value = records
    return mock


class TestKaptnAudit:

    def test_audit_empty(self, setup_mcp_test_env):
        with patch("bridge.mcp.tools.tool_audit.AuditLogger", return_value=_make_mock_audit([])):
            result = kaptn_audit()
        assert result["count"] == 0
        assert result["records"] == []

    def test_audit_returns_records(self, setup_mcp_test_env):
        records = [
            {
                "timestamp": "2026-03-08T07:00:00",
                "window_name": "Kaptn",
                "tab_id": "tab-1",
                "category": "command_unsafe",
                "action_text": "Run npm install",
                "decision": "approved",
                "rule_id": "allow-unsafe-commands",
            },
            {
                "timestamp": "2026-03-08T07:01:00",
                "window_name": "TelemetryMCPV2",
                "tab_id": "tab-2",
                "category": "file_write",
                "action_text": "Write src/app.py",
                "decision": "approved",
                "rule_id": "allow-file-write",
            },
        ]
        with patch("bridge.mcp.tools.tool_audit.AuditLogger", return_value=_make_mock_audit(records)):
            result = kaptn_audit()
        assert result["count"] == 2

    def test_audit_filter_window(self, setup_mcp_test_env):
        records = [
            {"timestamp": "", "window_name": "Kaptn", "tab_id": "", "category": "command_unsafe", "action_text": "", "decision": "approved", "rule_id": ""},
            {"timestamp": "", "window_name": "Other", "tab_id": "", "category": "command_unsafe", "action_text": "", "decision": "approved", "rule_id": ""},
        ]
        with patch("bridge.mcp.tools.tool_audit.AuditLogger", return_value=_make_mock_audit(records)):
            result = kaptn_audit(window="Kaptn")
        assert result["count"] == 1

    def test_audit_filter_category(self, setup_mcp_test_env):
        records = [
            {"timestamp": "", "window_name": "", "tab_id": "", "category": "command_unsafe", "action_text": "", "decision": "approved", "rule_id": ""},
            {"timestamp": "", "window_name": "", "tab_id": "", "category": "file_write", "action_text": "", "decision": "approved", "rule_id": ""},
        ]
        with patch("bridge.mcp.tools.tool_audit.AuditLogger", return_value=_make_mock_audit(records)):
            result = kaptn_audit(category="file_write")
        assert result["count"] == 1
        assert result["records"][0]["category"] == "file_write"

    def test_audit_filter_decision(self, setup_mcp_test_env):
        records = [
            {"timestamp": "", "window_name": "", "tab_id": "", "category": "", "action_text": "", "decision": "approved", "rule_id": ""},
            {"timestamp": "", "window_name": "", "tab_id": "", "category": "", "action_text": "", "decision": "denied", "rule_id": ""},
        ]
        with patch("bridge.mcp.tools.tool_audit.AuditLogger", return_value=_make_mock_audit(records)):
            result = kaptn_audit(decision="denied")
        assert result["count"] == 1

    def test_audit_limit_capped(self, setup_mcp_test_env):
        records = [
            {"timestamp": "", "window_name": "", "tab_id": "", "category": "", "action_text": "", "decision": "", "rule_id": ""}
            for _ in range(100)
        ]
        with patch("bridge.mcp.tools.tool_audit.AuditLogger", return_value=_make_mock_audit(records)):
            result = kaptn_audit(limit=5)
        assert result["count"] == 5

    def test_audit_max_cap_50(self, setup_mcp_test_env):
        records = [
            {"timestamp": "", "window_name": "", "tab_id": "", "category": "", "action_text": "", "decision": "", "rule_id": ""}
            for _ in range(100)
        ]
        with patch("bridge.mcp.tools.tool_audit.AuditLogger", return_value=_make_mock_audit(records)):
            result = kaptn_audit(limit=999)
        assert result["count"] == 50
