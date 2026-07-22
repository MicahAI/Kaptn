"""AutoPilot engine — orchestrates rule evaluation, limits, and loop detection."""

import logging

from bridge.autopilot.loop_detector import LoopDetector
from bridge.autopilot.rule_evaluator import RuleEvaluator
from bridge.models import ApprovalAction, ApprovalRequest, DecisionSource

logger = logging.getLogger(__name__)


class AutoPilotEngine:
    """Orchestrates automatic approval decisions for AI tool calls.

    Evaluates incoming approval requests against configured rules,
    checks limits, detects loops, and returns the appropriate action.
    """

    def __init__(
        self,
        rule_evaluator: RuleEvaluator,
        loop_detector: LoopDetector,
        enabled: bool = True,
    ) -> None:
        """Initialize the AutoPilot engine.

        Args:
            rule_evaluator: Evaluates requests against configured rules.
            loop_detector: Detects repeated action patterns.
            enabled: Whether AutoPilot is active.
        """
        self.rule_evaluator = rule_evaluator
        self.loop_detector = loop_detector
        self.enabled = enabled
        self._paused_windows: set[str] = set()

    def evaluate(self, request: ApprovalRequest) -> tuple[ApprovalAction, str | None, str]:
        """Evaluate an approval request and return the decision.

        Args:
            request: The parsed approval request from the IDE.

        Returns:
            Tuple of (action, rule_id, reason).
            - action: APPROVE, DENY, or ESCALATE
            - rule_id: ID of the matched rule, or None
            - reason: Human-readable explanation of the decision
        """
        if not self.enabled:
            logger.info("AutoPilot disabled — escalating")
            return ApprovalAction.ESCALATE, None, "autopilot_disabled"

        if request.window_name in self._paused_windows:
            logger.info("AutoPilot paused for window '%s' — escalating", request.window_name)
            return ApprovalAction.ESCALATE, None, "autopilot_paused"

        # Check for loops first
        is_loop = self.loop_detector.check(request)
        if is_loop:
            logger.warning(
                "Loop detected for '%s' in window '%s' — denying and pausing",
                request.action, request.window_name,
            )
            self._paused_windows.add(request.window_name)
            return ApprovalAction.DENY, None, "loop_detected"

        # Evaluate against rules
        action, rule_id, reason = self.rule_evaluator.evaluate(request)
        logger.info(
            "AutoPilot decision: %s (rule=%s, reason=%s, category=%s, action='%s')",
            action.value, rule_id, reason, request.category.value, request.action,
        )

        # Record this request in loop detector history
        self.loop_detector.record(request)

        return action, rule_id, reason

    def pause_window(self, window_name: str) -> None:
        """Pause AutoPilot for a specific window.

        Args:
            window_name: Name of the window to pause.
        """
        self._paused_windows.add(window_name)
        logger.info("AutoPilot paused for window '%s'", window_name)

    def resume_window(self, window_name: str) -> None:
        """Resume AutoPilot for a specific window.

        Args:
            window_name: Name of the window to resume.
        """
        self._paused_windows.discard(window_name)
        logger.info("AutoPilot resumed for window '%s'", window_name)

    def resume_all(self) -> None:
        """Resume AutoPilot for all paused windows."""
        self._paused_windows.clear()
        logger.info("AutoPilot resumed for all windows")

    def reset_limits(self) -> None:
        """Reset all limit counters and loop detector history."""
        self.rule_evaluator.reset_limits()
        self.loop_detector.clear()
        logger.info("AutoPilot limits and loop history reset")

    @property
    def paused_windows(self) -> set[str]:
        """Return the set of paused window names."""
        return set(self._paused_windows)

    @property
    def source(self) -> DecisionSource:
        """The decision source for audit records."""
        return DecisionSource.AUTOPILOT
