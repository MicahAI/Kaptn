"""Loop detector — detects repeated action patterns that indicate AI is stuck."""

import logging
from collections import deque

from bridge.models import ApprovalRequest

logger = logging.getLogger(__name__)


class LoopDetector:
    """Detects when the AI assistant is stuck in a loop.

    Tracks recent approval requests and flags patterns like:
    - Same action repeated N times in a row
    - Oscillation between two actions (A→B→A→B→A)
    """

    def __init__(
        self,
        same_action_threshold: int = 3,
        oscillation_threshold: int = 3,
        history_size: int = 20,
    ) -> None:
        """Initialize the loop detector.

        Args:
            same_action_threshold: Number of identical consecutive actions to flag as a loop.
            oscillation_threshold: Number of A→B alternations to flag as a loop.
            history_size: Maximum number of recent actions to track.
        """
        self.same_action_threshold = same_action_threshold
        self.oscillation_threshold = oscillation_threshold
        self.history_size = history_size
        self._history: deque[str] = deque(maxlen=history_size)

    def check(self, request: ApprovalRequest) -> bool:
        """Check if adding this request would create a loop pattern.

        Does NOT record the request — call record() separately after
        the decision is made.

        Args:
            request: The approval request to check.

        Returns:
            True if a loop is detected, False otherwise.
        """
        action_key = self._make_key(request)

        # Check same-action repetition
        if self._check_same_action(action_key):
            logger.warning("Loop: same action '%s' repeated %d times",
                           action_key, self.same_action_threshold)
            return True

        # Check oscillation
        if self._check_oscillation(action_key):
            logger.warning("Loop: oscillation detected involving '%s'", action_key)
            return True

        return False

    def record(self, request: ApprovalRequest) -> None:
        """Record a request in the history.

        Args:
            request: The approval request to record.
        """
        action_key = self._make_key(request)
        self._history.append(action_key)

    def clear(self) -> None:
        """Clear the action history."""
        self._history.clear()
        logger.debug("Loop detector history cleared")

    def _make_key(self, request: ApprovalRequest) -> str:
        """Create a hashable key from a request for comparison.

        Uses category + a normalized context snippet so different commands
        produce different keys (e.g. 'npm install' vs 'echo hello'), while
        the same command repeated still triggers loop detection.

        Args:
            request: The approval request.

        Returns:
            A string key combining category and context.
        """
        context = ""
        if request.details:
            raw = request.details.get("context", "")
            # Normalize: lowercase, strip whitespace, take first 80 chars
            context = raw.lower().strip()[:80]
        return f"{request.category.value}:{context or request.action}"

    def _check_same_action(self, action_key: str) -> bool:
        """Check if the same action has been repeated consecutively.

        Args:
            action_key: The key for the current action.

        Returns:
            True if adding this action would exceed the threshold.
        """
        if len(self._history) < self.same_action_threshold - 1:
            return False

        # Check the last N-1 entries (the current one hasn't been added yet)
        count_needed = self.same_action_threshold - 1
        recent = list(self._history)[-count_needed:]
        return all(key == action_key for key in recent)

    def _check_oscillation(self, action_key: str) -> bool:
        """Check for A→B→A→B oscillation pattern.

        Detects when the current action would complete an alternating sequence.
        For threshold=3, detects patterns like B→A→B→A→(B) (5 total elements).

        Args:
            action_key: The key for the current action.

        Returns:
            True if an oscillation pattern is detected.
        """
        # Total pattern length is (threshold * 2) - 1.
        # Current action is the final element, so we need (threshold * 2) - 2 in history.
        needed = (self.oscillation_threshold * 2) - 2
        if len(self._history) < needed:
            return False

        recent = list(self._history)[-needed:]

        # First element of recent should equal action_key
        # (pattern starts and ends with the same action)
        if recent[0] != action_key:
            return False

        # Second element must differ (the "other" action)
        other_key = recent[1]
        if other_key == action_key:
            return False

        # Verify strict alternation: action_key, other, action_key, other, ...
        for i, key in enumerate(recent):
            expected = action_key if i % 2 == 0 else other_key
            if key != expected:
                return False

        return True

    @property
    def history(self) -> list[str]:
        """Return the current action history."""
        return list(self._history)
