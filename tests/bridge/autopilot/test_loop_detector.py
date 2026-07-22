"""Tests for LoopDetector — detecting repeated action patterns."""


from bridge.autopilot.loop_detector import LoopDetector
from bridge.models import ApprovalCategory, ApprovalRequest


class TestLoopDetector:
    """Tests for the LoopDetector class."""

    def _make_request(self, action: str = "Edit main.py",
                      category: str = "file_write") -> ApprovalRequest:
        """Helper to create an ApprovalRequest."""
        return ApprovalRequest(
            category=ApprovalCategory(category),
            action=action,
        )

    def test_no_loop_on_empty_history(self):
        """No loop detected when history is empty."""
        detector = LoopDetector()
        assert detector.check(self._make_request()) is False

    def test_no_loop_with_different_actions(self):
        """No loop when actions are all different."""
        detector = LoopDetector(same_action_threshold=3)
        detector.record(self._make_request("Edit a.py"))
        detector.record(self._make_request("Edit b.py"))

        assert detector.check(self._make_request("Edit c.py")) is False

    def test_same_action_loop_detected(self):
        """Loop detected when same action repeats N times."""
        detector = LoopDetector(same_action_threshold=3)

        req = self._make_request("Edit main.py")
        detector.record(req)
        detector.record(req)

        # Third identical request triggers loop
        assert detector.check(req) is True

    def test_same_action_below_threshold(self):
        """No loop when same action count is below threshold."""
        detector = LoopDetector(same_action_threshold=3)

        req = self._make_request("Edit main.py")
        detector.record(req)

        # Only 1 in history + 1 current = 2, need 3
        assert detector.check(req) is False

    def test_same_action_broken_by_different(self):
        """Consecutive check resets when a different action occurs."""
        detector = LoopDetector(same_action_threshold=3)

        req_a = self._make_request("Edit a.py")
        req_b = self._make_request("Edit b.py")

        detector.record(req_a)
        detector.record(req_a)
        detector.record(req_b)  # Breaks the streak
        detector.record(req_a)

        # Only 1 consecutive 'a' before this check
        assert detector.check(req_a) is False

    def test_oscillation_detected(self):
        """Loop detected on A→B→A→B→A pattern."""
        detector = LoopDetector(oscillation_threshold=3)

        req_a = self._make_request("Edit a.py")
        req_b = self._make_request("Edit b.py")

        # Build pattern: B, A, B, A — then check for A
        detector.record(req_b)
        detector.record(req_a)
        detector.record(req_b)
        detector.record(req_a)

        # Current would be B, completing B→A→B→A→B
        assert detector.check(req_b) is True

    def test_oscillation_below_threshold(self):
        """No oscillation detected when alternations are below threshold."""
        detector = LoopDetector(oscillation_threshold=3)

        req_a = self._make_request("Edit a.py")
        req_b = self._make_request("Edit b.py")

        detector.record(req_a)
        detector.record(req_b)

        # Only 1 alternation, need 3
        assert detector.check(req_a) is False

    def test_clear_resets_history(self):
        """clear() removes all history."""
        detector = LoopDetector(same_action_threshold=2)

        req = self._make_request("Edit main.py")
        detector.record(req)

        detector.clear()

        # After clear, no loop should be detected
        assert detector.check(req) is False
        assert len(detector.history) == 0

    def test_history_property(self):
        """history property returns a copy of the action history."""
        detector = LoopDetector()

        detector.record(self._make_request("Edit a.py"))
        detector.record(self._make_request("Edit b.py"))

        history = detector.history
        assert len(history) == 2
        assert "file_write:Edit a.py" in history[0]

    def test_history_size_limit(self):
        """History is bounded by history_size."""
        detector = LoopDetector(history_size=5)

        for i in range(10):
            detector.record(self._make_request(f"Edit {i}.py"))

        assert len(detector.history) == 5

    def test_custom_threshold(self):
        """Custom same_action_threshold is respected."""
        detector = LoopDetector(same_action_threshold=5)

        req = self._make_request("Edit main.py")
        for _ in range(3):
            detector.record(req)

        # 3 in history + 1 current = 4, need 5
        assert detector.check(req) is False

        detector.record(req)  # Now 4 in history

        # 4 in history + 1 current = 5, triggers loop
        assert detector.check(req) is True
