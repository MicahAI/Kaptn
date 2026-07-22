"""Tests for RuleEvaluator — matching approval requests against rules."""


from bridge.autopilot.rule_evaluator import RuleEvaluator
from bridge.models import ApprovalAction, ApprovalCategory, ApprovalRequest


class TestRuleEvaluator:
    """Tests for the RuleEvaluator class."""

    def _make_request(self, category: str = "file_write", action: str = "Edit file.py",
                      details: dict | None = None, window: str = "") -> ApprovalRequest:
        """Helper to create an ApprovalRequest."""
        return ApprovalRequest(
            category=ApprovalCategory(category),
            action=action,
            details=details or {},
            window_name=window,
        )

    def test_no_rules_escalates(self):
        """With no rules, all requests are escalated."""
        evaluator = RuleEvaluator(rules=[])
        action, rule_id, reason = evaluator.evaluate(self._make_request())
        assert action == ApprovalAction.ESCALATE
        assert rule_id is None
        assert reason == "no_matching_rule"

    def test_simple_approve_rule(self):
        """A simple approve rule matches by category."""
        rules = [{"id": "allow-writes", "category": "file_write", "action": "approve"}]
        evaluator = RuleEvaluator(rules=rules)
        action, rule_id, reason = evaluator.evaluate(self._make_request())
        assert action == ApprovalAction.APPROVE
        assert rule_id == "allow-writes"
        assert reason == "rule_matched"

    def test_simple_deny_rule(self):
        """A deny rule blocks the request."""
        rules = [{"id": "block-deletes", "category": "file_delete", "action": "deny"}]
        evaluator = RuleEvaluator(rules=rules)
        action, rule_id, _ = evaluator.evaluate(
            self._make_request(category="file_delete", action="Delete file.py")
        )
        assert action == ApprovalAction.DENY
        assert rule_id == "block-deletes"

    def test_first_matching_rule_wins(self):
        """Rules are checked in order — first match wins."""
        rules = [
            {"id": "deny-all-files", "category": "file_write", "action": "deny"},
            {"id": "allow-all-files", "category": "file_write", "action": "approve"},
        ]
        evaluator = RuleEvaluator(rules=rules)
        action, rule_id, _ = evaluator.evaluate(self._make_request())
        assert action == ApprovalAction.DENY
        assert rule_id == "deny-all-files"

    def test_category_mismatch_skips_rule(self):
        """Rules that don't match the category are skipped."""
        rules = [
            {"id": "allow-commands", "category": "command_safe", "action": "approve"},
            {"id": "allow-writes", "category": "file_write", "action": "approve"},
        ]
        evaluator = RuleEvaluator(rules=rules)
        action, rule_id, _ = evaluator.evaluate(self._make_request(category="file_write"))
        assert rule_id == "allow-writes"

    def test_wildcard_category(self):
        """A rule with category '*' matches any category."""
        rules = [{"id": "approve-all", "category": "*", "action": "approve"}]
        evaluator = RuleEvaluator(rules=rules)

        action, _, _ = evaluator.evaluate(self._make_request(category="file_write"))
        assert action == ApprovalAction.APPROVE

        action, _, _ = evaluator.evaluate(self._make_request(category="command_safe"))
        assert action == ApprovalAction.APPROVE

    def test_path_pattern_match(self):
        """Path patterns filter file operations."""
        rules = [{
            "id": "allow-python",
            "category": "file_write",
            "action": "approve",
            "conditions": {"path_patterns": ["**/*.py"]},
        }]
        evaluator = RuleEvaluator(rules=rules)

        # Match
        action, _, _ = evaluator.evaluate(
            self._make_request(details={"path": "bridge/main.py"})
        )
        assert action == ApprovalAction.APPROVE

        # No match
        action, _, _ = evaluator.evaluate(
            self._make_request(details={"path": "package.json"})
        )
        assert action == ApprovalAction.ESCALATE

    def test_exclude_pattern(self):
        """Exclude patterns block specific paths."""
        rules = [{
            "id": "allow-but-not-env",
            "category": "file_write",
            "action": "approve",
            "conditions": {"exclude_patterns": ["**/.env*"]},
        }]
        evaluator = RuleEvaluator(rules=rules)

        action, _, _ = evaluator.evaluate(
            self._make_request(details={"path": "bridge/main.py"})
        )
        assert action == ApprovalAction.APPROVE

        action, _, _ = evaluator.evaluate(
            self._make_request(details={"path": ".env.local"})
        )
        assert action == ApprovalAction.ESCALATE

    def test_command_pattern(self):
        """Command patterns match against command text."""
        rules = [{
            "id": "block-rm",
            "category": "command_unsafe",
            "action": "deny",
            "conditions": {"command_patterns": ["rm *", "sudo *"]},
        }]
        evaluator = RuleEvaluator(rules=rules)

        action, _, _ = evaluator.evaluate(
            self._make_request(category="command_unsafe", action="rm -rf node_modules",
                               details={"command": "rm -rf node_modules"})
        )
        assert action == ApprovalAction.DENY

    def test_session_limit(self):
        """max_per_session limit escalates after threshold."""
        rules = [{
            "id": "limited-writes",
            "category": "file_write",
            "action": "approve",
            "limits": {"max_per_session": 3},
        }]
        evaluator = RuleEvaluator(rules=rules)

        # First 3 should approve
        for i in range(3):
            action, _, _ = evaluator.evaluate(self._make_request(action=f"edit {i}"))
            assert action == ApprovalAction.APPROVE, f"Request {i} should be approved"

        # 4th should escalate
        action, rule_id, reason = evaluator.evaluate(self._make_request(action="edit 3"))
        assert action == ApprovalAction.ESCALATE
        assert "limit_exceeded" in reason
        assert "max_per_session" in reason

    def test_reset_limits(self):
        """reset_limits clears all counters."""
        rules = [{
            "id": "limited",
            "category": "file_write",
            "action": "approve",
            "limits": {"max_per_session": 1},
        }]
        evaluator = RuleEvaluator(rules=rules)

        action, _, _ = evaluator.evaluate(self._make_request())
        assert action == ApprovalAction.APPROVE

        action, _, _ = evaluator.evaluate(self._make_request())
        assert action == ApprovalAction.ESCALATE

        evaluator.reset_limits()

        action, _, _ = evaluator.evaluate(self._make_request())
        assert action == ApprovalAction.APPROVE

    def test_get_limit_status(self):
        """get_limit_status returns current counter values."""
        rules = [{
            "id": "tracked",
            "category": "file_write",
            "action": "approve",
            "limits": {"max_per_session": 10},
        }]
        evaluator = RuleEvaluator(rules=rules)

        evaluator.evaluate(self._make_request())
        evaluator.evaluate(self._make_request())

        status = evaluator.get_limit_status()
        assert "tracked" in status
        assert status["tracked"]["session_count"] == 2

    def test_escalate_action(self):
        """A rule with action 'escalate' explicitly escalates."""
        rules = [{"id": "escalate-unknown", "category": "unknown", "action": "escalate"}]
        evaluator = RuleEvaluator(rules=rules)
        action, rule_id, _ = evaluator.evaluate(self._make_request(category="unknown"))
        assert action == ApprovalAction.ESCALATE
        assert rule_id == "escalate-unknown"
