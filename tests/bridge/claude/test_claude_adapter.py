"""Tests for the Claude Code adapter — hook events through AutoPilot."""

import pytest

from bridge.audit.audit_logger import AuditLogger
from bridge.autopilot.auto_pilot_engine import AutoPilotEngine
from bridge.autopilot.escalation_handler import EscalationHandler
from bridge.autopilot.loop_detector import LoopDetector
from bridge.autopilot.rule_evaluator import RuleEvaluator
from bridge.claude.claude_adapter import ClaudeAdapter

RULES = [
    {"id": "allow-reads", "category": "file_read", "action": "approve"},
    {"id": "allow-writes", "category": "file_write", "action": "approve",
     "limits": {"max_per_session": 2}},
    {"id": "block-deletes", "category": "file_delete", "action": "deny"},
    {"id": "allow-safe", "category": "command_safe", "action": "approve"},
]


def make_event(tool_name="Read", tool_input=None, event_name="PreToolUse"):
    return {
        "session_id": "sess-1",
        "cwd": "/Users/wilson/proj",
        "hook_event_name": event_name,
        "tool_name": tool_name,
        "tool_input": tool_input if tool_input is not None else {"file_path": "/tmp/a.py"},
    }


@pytest.fixture
def adapter():
    autopilot = AutoPilotEngine(
        rule_evaluator=RuleEvaluator(RULES),
        loop_detector=LoopDetector(same_action_threshold=3),
    )
    audit = AuditLogger(db_path=":memory:")
    yield ClaudeAdapter(autopilot, audit, EscalationHandler())
    audit.close()


class TestDecisions:
    def test_approve_maps_to_allow(self, adapter):
        result = adapter.handle_hook_event(make_event("Read"))
        output = result["hookSpecificOutput"]
        assert output["hookEventName"] == "PreToolUse"
        assert output["permissionDecision"] == "allow"
        assert "allow-reads" in output["permissionDecisionReason"]

    def test_deny_maps_to_deny(self, adapter):
        result = adapter.handle_hook_event(
            make_event("Bash", {"command": "rm -rf build"})
        )
        output = result["hookSpecificOutput"]
        assert output["permissionDecision"] == "deny"
        assert "block-deletes" in output["permissionDecisionReason"]

    def test_no_rule_maps_to_ask(self, adapter):
        result = adapter.handle_hook_event(
            make_event("Bash", {"command": "npm install"})
        )
        output = result["hookSpecificOutput"]
        assert output["permissionDecision"] == "ask"
        assert "no_matching_rule" in output["permissionDecisionReason"]

    def test_escalation_handler_notified_on_ask(self, adapter):
        adapter.handle_hook_event(make_event("Bash", {"command": "npm install"}))
        pending = adapter.escalation.get_pending()
        assert len(pending) == 1
        assert pending[0].reason == "no_matching_rule"

    def test_limit_exceeded_becomes_ask(self, adapter):
        event = make_event("Write", {"file_path": "/tmp/w.py"})
        assert adapter.handle_hook_event(event)["hookSpecificOutput"]["permissionDecision"] == "allow"
        event2 = make_event("Write", {"file_path": "/tmp/w2.py"})
        assert adapter.handle_hook_event(event2)["hookSpecificOutput"]["permissionDecision"] == "allow"
        event3 = make_event("Write", {"file_path": "/tmp/w3.py"})
        output = adapter.handle_hook_event(event3)["hookSpecificOutput"]
        assert output["permissionDecision"] == "ask"
        assert "limit_exceeded" in output["permissionDecisionReason"]


class TestEventFiltering:
    def test_non_pretooluse_ignored(self, adapter):
        assert adapter.handle_hook_event(make_event(event_name="PostToolUse")) is None
        assert adapter.handle_hook_event(make_event(event_name="Stop")) is None

    def test_non_dict_ignored(self, adapter):
        assert adapter.handle_hook_event("not a dict") is None
        assert adapter.handle_hook_event(None) is None

    def test_missing_fields_still_evaluates(self, adapter):
        result = adapter.handle_hook_event({"hook_event_name": "PreToolUse"})
        # Empty tool name → unknown category → no rule → ask
        assert result["hookSpecificOutput"]["permissionDecision"] == "ask"


class TestAuditAndContext:
    def test_every_decision_audited(self, adapter):
        adapter.handle_hook_event(make_event("Read"))
        adapter.handle_hook_event(make_event("Bash", {"command": "rm x"}))
        adapter.handle_hook_event(make_event("Bash", {"command": "npm install"}))
        assert adapter.audit.get_count() == 3

    def test_audit_record_details(self, adapter):
        adapter.handle_hook_event(make_event("Read"))
        record = adapter.audit.get_recent(limit=1)[0]
        assert record["window_name"] == "claude:proj"
        assert record["mode"] == "claude"
        assert record["tab_id"] == "sess-1"
        assert record["category"] == "file_read"
        assert record["decision"] == "approve"

    def test_window_name_without_cwd(self, adapter):
        event = make_event("Read")
        event["cwd"] = ""
        adapter.handle_hook_event(event)
        assert adapter.audit.get_recent(limit=1)[0]["window_name"] == "claude"


class TestLoopDetection:
    def test_repeated_action_denied_as_loop(self, adapter):
        event = make_event("Bash", {"command": "cat same.txt"})
        assert adapter.handle_hook_event(event)["hookSpecificOutput"]["permissionDecision"] == "allow"
        assert adapter.handle_hook_event(event)["hookSpecificOutput"]["permissionDecision"] == "allow"
        output = adapter.handle_hook_event(event)["hookSpecificOutput"]
        assert output["permissionDecision"] == "deny"
        assert "loop_detected" in output["permissionDecisionReason"]
        loops = adapter.audit.get_loops()
        assert len(loops) == 1
