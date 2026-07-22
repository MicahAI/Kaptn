"""Tests for AutoPilotEngine — orchestration of rules, limits, and loop detection."""


from bridge.autopilot.auto_pilot_engine import AutoPilotEngine
from bridge.autopilot.loop_detector import LoopDetector
from bridge.autopilot.rule_evaluator import RuleEvaluator
from bridge.models import ApprovalAction, ApprovalCategory, ApprovalRequest, DecisionSource


class TestAutoPilotEngine:
    """Tests for the AutoPilotEngine class."""

    def _make_request(self, action: str = "Edit main.py",
                      category: str = "file_write", window: str = "TestProject") -> ApprovalRequest:
        """Helper to create an ApprovalRequest."""
        return ApprovalRequest(
            category=ApprovalCategory(category),
            action=action,
            window_name=window,
        )

    def _make_engine(self, rules: list[dict] | None = None, enabled: bool = True,
                     same_action_threshold: int = 3) -> AutoPilotEngine:
        """Helper to create an AutoPilotEngine with given rules."""
        rules = rules or [{"id": "allow-all", "category": "*", "action": "approve"}]
        return AutoPilotEngine(
            rule_evaluator=RuleEvaluator(rules),
            loop_detector=LoopDetector(same_action_threshold=same_action_threshold),
            enabled=enabled,
        )

    def test_disabled_escalates(self):
        """When disabled, all requests are escalated."""
        engine = self._make_engine(enabled=False)
        action, rule_id, reason = engine.evaluate(self._make_request())
        assert action == ApprovalAction.ESCALATE
        assert reason == "autopilot_disabled"

    def test_enabled_applies_rules(self):
        """When enabled, rules are evaluated normally."""
        engine = self._make_engine()
        action, rule_id, reason = engine.evaluate(self._make_request())
        assert action == ApprovalAction.APPROVE
        assert rule_id == "allow-all"

    def test_loop_detection_denies(self):
        """Loop detection overrides rule evaluation with DENY."""
        engine = self._make_engine(same_action_threshold=3)
        req = self._make_request()

        engine.evaluate(req)
        engine.evaluate(req)

        # Third identical request triggers loop
        action, _, reason = engine.evaluate(req)
        assert action == ApprovalAction.DENY
        assert reason == "loop_detected"

    def test_loop_detection_pauses_window(self):
        """After loop detection, the window is paused."""
        engine = self._make_engine(same_action_threshold=3)
        req = self._make_request(window="MyProject")

        engine.evaluate(req)
        engine.evaluate(req)
        engine.evaluate(req)  # Loop detected, window paused

        assert "MyProject" in engine.paused_windows

    def test_paused_window_escalates(self):
        """Paused windows always escalate."""
        engine = self._make_engine()
        engine.pause_window("PausedProject")

        action, _, reason = engine.evaluate(
            self._make_request(window="PausedProject")
        )
        assert action == ApprovalAction.ESCALATE
        assert reason == "autopilot_paused"

    def test_resume_window(self):
        """Resuming a window allows rules to apply again."""
        engine = self._make_engine()
        engine.pause_window("MyProject")

        action, _, _ = engine.evaluate(self._make_request(window="MyProject"))
        assert action == ApprovalAction.ESCALATE

        engine.resume_window("MyProject")

        action, _, _ = engine.evaluate(self._make_request(window="MyProject"))
        assert action == ApprovalAction.APPROVE

    def test_resume_all(self):
        """resume_all clears all paused windows."""
        engine = self._make_engine()
        engine.pause_window("A")
        engine.pause_window("B")

        engine.resume_all()
        assert len(engine.paused_windows) == 0

    def test_reset_limits(self):
        """reset_limits delegates to rule evaluator."""
        rules = [{"id": "limited", "category": "file_write", "action": "approve",
                   "limits": {"max_per_session": 1}}]
        engine = self._make_engine(rules=rules)

        action, _, _ = engine.evaluate(self._make_request())
        assert action == ApprovalAction.APPROVE

        action, _, _ = engine.evaluate(self._make_request())
        assert action == ApprovalAction.ESCALATE

        engine.reset_limits()

        action, _, _ = engine.evaluate(self._make_request())
        assert action == ApprovalAction.APPROVE

    def test_source_is_autopilot(self):
        """Source property returns AUTOPILOT."""
        engine = self._make_engine()
        assert engine.source == DecisionSource.AUTOPILOT

    def test_different_windows_independent(self):
        """Pausing one window doesn't affect others."""
        engine = self._make_engine()
        engine.pause_window("PausedProject")

        action_paused, _, _ = engine.evaluate(self._make_request(window="PausedProject"))
        action_active, _, _ = engine.evaluate(self._make_request(window="ActiveProject"))

        assert action_paused == ApprovalAction.ESCALATE
        assert action_active == ApprovalAction.APPROVE

    def test_no_rules_escalates(self):
        """With no matching rules, requests are escalated."""
        engine = self._make_engine(rules=[
            {"id": "commands-only", "category": "command_safe", "action": "approve"}
        ])
        action, _, reason = engine.evaluate(self._make_request(category="file_write"))
        assert action == ApprovalAction.ESCALATE
        assert reason == "no_matching_rule"
