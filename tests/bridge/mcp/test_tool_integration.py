"""Integration tests: temp rules → RuleEvaluator precedence."""

import time

from bridge.autopilot.rule_evaluator import RuleEvaluator
from bridge.autopilot.temp_rule_manager import TempRuleManager
from bridge.models import ApprovalAction, ApprovalCategory, ApprovalRequest


class TestTempRulesIntegration:

    def test_temp_rule_takes_precedence_over_static(self):
        """Temp rules should be checked before static rules in RuleEvaluator."""
        static_rules = [
            {"id": "escalate-all", "category": "*", "action": "escalate"},
        ]
        evaluator = RuleEvaluator(static_rules)
        evaluator.temp_rules = TempRuleManager()

        request = ApprovalRequest(
            category=ApprovalCategory.COMMAND_UNSAFE,
            action="Run npm install",
            window_name="Kaptn",
        )

        # Without temp rule → escalate (static rule)
        action, rule_id, reason = evaluator.evaluate(request)
        assert action == ApprovalAction.ESCALATE

        # Add temp rule → approve (overrides static)
        evaluator.temp_rules.create_rule(category="command_unsafe", minutes=10, window="Kaptn")
        action, rule_id, reason = evaluator.evaluate(request)
        assert action == ApprovalAction.APPROVE
        assert reason == "temp_rule_matched"

    def test_temp_rule_expired_falls_through(self):
        """Expired temp rules should fall through to static rules."""
        static_rules = [
            {"id": "approve-safe", "category": "command_safe", "action": "approve"},
        ]
        evaluator = RuleEvaluator(static_rules)
        evaluator.temp_rules = TempRuleManager()

        rule = evaluator.temp_rules.create_rule(category="command_safe", minutes=10, window="Kaptn")
        rule.expires_at = time.time() - 1  # force expire

        request = ApprovalRequest(
            category=ApprovalCategory.COMMAND_SAFE,
            action="Run echo hello",
            window_name="Kaptn",
        )
        action, rule_id, reason = evaluator.evaluate(request)
        assert action == ApprovalAction.APPROVE
        assert rule_id == "approve-safe"
        assert reason == "rule_matched"  # static rule matched

    def test_temp_rule_count_exhaustion(self):
        """Temp rule with max_count should auto-expire after N approvals."""
        evaluator = RuleEvaluator([])
        evaluator.temp_rules = TempRuleManager()
        evaluator.temp_rules.create_rule(category="command_safe", minutes=10, max_count=2)

        request = ApprovalRequest(
            category=ApprovalCategory.COMMAND_SAFE,
            action="Run echo hello",
            window_name="Kaptn",
        )

        # First two should approve via temp rule
        action, _, reason = evaluator.evaluate(request)
        assert action == ApprovalAction.APPROVE
        assert reason == "temp_rule_matched"

        action, _, reason = evaluator.evaluate(request)
        assert action == ApprovalAction.APPROVE

        # Third should escalate (temp rule exhausted, no static rules)
        action, _, reason = evaluator.evaluate(request)
        assert action == ApprovalAction.ESCALATE
        assert reason == "no_matching_rule"
