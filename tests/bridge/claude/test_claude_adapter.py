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
    {"id": "hard-block-secret-deletes", "category": "file_delete", "action": "deny",
     "hard_deny": True, "conditions": {"command_patterns": ["*secret*"]}},
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

    def test_rule_deny_maps_to_overridable_ask(self, adapter):
        # IDE parity: a deny rule is a recommendation the user can override,
        # so it surfaces Claude Code's permission prompt instead of blocking.
        result = adapter.handle_hook_event(
            make_event("Bash", {"command": "rm -rf build"})
        )
        output = result["hookSpecificOutput"]
        assert output["permissionDecision"] == "ask"
        assert "recommends denying" in output["permissionDecisionReason"]
        assert "block-deletes" in output["permissionDecisionReason"]

    def test_hard_deny_rule_still_blocks(self, adapter):
        result = adapter.handle_hook_event(
            make_event("Bash", {"command": "rm secret.pem"})
        )
        output = result["hookSpecificOutput"]
        assert output["permissionDecision"] == "deny"
        assert "hard-block-secret-deletes" in output["permissionDecisionReason"]
        assert "recommends" not in output["permissionDecisionReason"]

    def test_soft_deny_notifies_escalation_handler(self, adapter):
        adapter.handle_hook_event(make_event("Bash", {"command": "rm -rf build"}))
        pending = adapter.escalation.get_pending()
        assert len(pending) == 1
        assert pending[0].reason == "deny_recommended:rule_matched"
        assert pending[0].rule_id == "block-deletes"

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


class TestPerSessionLimits:
    def test_sessions_do_not_share_caps(self, adapter):
        # Session A exhausts its 2-write allowance
        for path in ("/tmp/a1.py", "/tmp/a2.py"):
            event = make_event("Write", {"file_path": path})
            event["session_id"] = "session-A"
            assert adapter.handle_hook_event(event)["hookSpecificOutput"]["permissionDecision"] == "allow"
        event = make_event("Write", {"file_path": "/tmp/a3.py"})
        event["session_id"] = "session-A"
        assert adapter.handle_hook_event(event)["hookSpecificOutput"]["permissionDecision"] == "ask"

        # Session B starts fresh — full allowance despite A being capped
        event = make_event("Write", {"file_path": "/tmp/b1.py"})
        event["session_id"] = "session-B"
        assert adapter.handle_hook_event(event)["hookSpecificOutput"]["permissionDecision"] == "allow"

    def test_limit_status_reports_scopes(self, adapter):
        event = make_event("Write", {"file_path": "/tmp/a.py"})
        event["session_id"] = "session-A"
        adapter.handle_hook_event(event)
        status = adapter.autopilot.rule_evaluator.get_limit_status()
        assert status["allow-writes"]["scopes"] == {"session-A": 1}


class TestReset:
    def test_reset_clears_limits(self, adapter):
        event1 = make_event("Write", {"file_path": "/tmp/w.py"})
        event2 = make_event("Write", {"file_path": "/tmp/w2.py"})
        event3 = make_event("Write", {"file_path": "/tmp/w3.py"})
        adapter.handle_hook_event(event1)
        adapter.handle_hook_event(event2)
        assert adapter.handle_hook_event(event3)["hookSpecificOutput"]["permissionDecision"] == "ask"

        assert adapter.reset() == {"status": "reset"}
        event4 = make_event("Write", {"file_path": "/tmp/w4.py"})
        assert adapter.handle_hook_event(event4)["hookSpecificOutput"]["permissionDecision"] == "allow"

    def test_reset_clears_loop_pause(self, adapter):
        event = make_event("Bash", {"command": "cat same.txt"})
        for _ in range(3):
            adapter.handle_hook_event(event)  # third one trips the loop → pause
        other = make_event("Read")
        assert adapter.handle_hook_event(other)["hookSpecificOutput"]["permissionDecision"] == "ask"

        adapter.reset()
        assert adapter.handle_hook_event(other)["hookSpecificOutput"]["permissionDecision"] == "allow"


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
