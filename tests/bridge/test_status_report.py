"""Tests for kaptn status report and the help command."""

import json

import pytest
from click.testing import CliRunner

from bridge import status_report
from bridge.audit.audit_logger import AuditLogger
from bridge.autopilot.auto_pilot_engine import AutoPilotEngine
from bridge.autopilot.loop_detector import LoopDetector
from bridge.autopilot.rule_evaluator import RuleEvaluator
from bridge.claude.claude_adapter import ClaudeAdapter
from bridge.claude.hook_server import ClaudeHookServer
from bridge.main import cli
from bridge.models import ApprovalAction, ApprovalCategory, ApprovalRequest, DecisionSource

RULES = [
    {"id": "allow-writes", "category": "file_write", "action": "approve",
     "limits": {"max_per_session": 5}},
]


@pytest.fixture
def audit():
    logger = AuditLogger(db_path=":memory:")
    yield logger
    logger.close()


@pytest.fixture
def server(audit):
    autopilot = AutoPilotEngine(
        rule_evaluator=RuleEvaluator(RULES), loop_detector=LoopDetector()
    )
    srv = ClaudeHookServer(ClaudeAdapter(autopilot, audit), port=0)
    srv.start()
    yield srv
    srv.stop()


def record_decision(audit, decision=ApprovalAction.APPROVE):
    audit.create_record(
        request=ApprovalRequest(
            category=ApprovalCategory.FILE_WRITE, action="Write /tmp/x",
            window_name="claude:test",
        ),
        decision=decision,
        source=DecisionSource.AUTOPILOT,
    )


class TestFetchLiveStatus:
    def test_reachable(self, server):
        live = status_report.fetch_live_status(server.port)
        assert live["autopilot_enabled"] is True
        assert live["rules_loaded"] == 1
        assert live["paused_windows"] == []

    def test_unreachable(self):
        assert status_report.fetch_live_status(port=1, timeout=1) is None


class TestAuditSummary:
    def test_tallies_decisions(self, audit):
        record_decision(audit, ApprovalAction.APPROVE)
        record_decision(audit, ApprovalAction.APPROVE)
        record_decision(audit, ApprovalAction.DENY)
        summary = status_report.audit_summary(audit)
        assert summary["total"] == 3
        assert summary["tally"] == {"approve": 2, "deny": 1}

    def test_empty(self, audit):
        summary = status_report.audit_summary(audit)
        assert summary["total"] == 0
        assert summary["tally"] == {}


class TestBuildReport:
    def make_cfg(self, port):
        return {
            "cdp_port": 1,  # nothing listening
            "claude": {"enabled": True, "hook_port": port,
                       "launchd_label": "com.test.nonexistent"},
            "autopilot": {"enabled": True, "rules": RULES,
                          "loop_detection": {"enabled": True,
                                             "same_action_threshold": 3,
                                             "oscillation_threshold": 3}},
        }

    def test_report_with_live_server_and_usage(self, server, audit):
        # Generate usage in a session so the live counters show up
        event = {
            "session_id": "abcdef12-3456-7890-abcd-ef1234567890",
            "cwd": "/tmp/proj", "hook_event_name": "PreToolUse",
            "tool_name": "Write", "tool_input": {"file_path": "/tmp/a.py"},
        }
        server.adapter.handle_hook_event(event)

        lines = status_report.build_report(self.make_cfg(server.port), audit)
        text = "\n".join(lines)
        assert "✅ Claude hook server: healthy" in text
        assert "AutoPilot ON, 1 rules" in text
        assert "⚪ CDP: no IDE on port 1" in text
        assert "allow-writes" in text
        assert "1/5 used" in text
        assert "abcdef12…: 1" in text
        assert "total decisions: 1" in text  # the hook event was audited

    def test_report_with_server_down(self, audit):
        lines = status_report.build_report(self.make_cfg(port=1), audit)
        text = "\n".join(lines)
        assert "❌ Claude hook server: not reachable on port 1" in text
        assert "(server not running — no live counters)" in text

    def test_report_no_usage_yet(self, server, audit):
        lines = status_report.build_report(self.make_cfg(server.port), audit)
        assert "  no rule usage recorded yet" in lines

    def test_short_scope(self):
        assert status_report._short_scope("small") == "small"
        long_scope = "abcdef12-3456-7890-abcd-ef1234567890"
        assert status_report._short_scope(long_scope) == "abcdef12…"


class TestCliCommands:
    def test_status_command(self, server, tmp_path):
        config = tmp_path / "kaptn.config.json"
        config.write_text(json.dumps({
            "cdp_port": 1,
            "audit_db": str(tmp_path / "audit.db"),
            "claude": {"enabled": True, "hook_port": server.port,
                       "launchd_label": "com.test.nonexistent"},
        }))
        result = CliRunner().invoke(cli, ["status", "--config", str(config)])
        assert result.exit_code == 0
        assert "Kaptn Status" in result.output
        assert "── Servers ──" in result.output
        assert "── AutoPilot config ──" in result.output
        assert "── Usage (live) ──" in result.output
        assert "── Audit ──" in result.output

    def test_help_command(self):
        result = CliRunner().invoke(cli, ["help"])
        assert result.exit_code == 0
        for expected in ("kaptn start", "kaptn stop", "kaptn reset", "kaptn status",
                         "kaptn log", "kaptn claude", "install", "serve", "kaptn mcp"):
            assert expected in result.output
