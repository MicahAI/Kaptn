"""Tests for AutoReplyEngine — conversational stall detection and auto-reply."""

import time

import pytest

from bridge.autopilot.auto_reply_engine import AutoReplyEngine, DEFAULT_AUTO_REPLY_RULES
from bridge.autopilot.auto_reply_rule import AutoReplyRule


class TestAutoReplyEngine:
    """Tests for AutoReplyEngine.check()."""

    def _make_engine(self, rules=None, cooldown=0.0, max_consecutive=5):
        """Helper to create an engine with minimal cooldown for testing."""
        if rules is None:
            rules = [
                AutoReplyRule(id="proceed", pattern="should I proceed", reply="yes"),
                AutoReplyRule(id="continue", pattern="shall I continue|want me to continue", reply="yes, continue"),
            ]
        return AutoReplyEngine(rules=rules, cooldown_seconds=cooldown, max_consecutive=max_consecutive)

    def test_match_returns_reply_and_rule_id(self):
        engine = self._make_engine()
        reply, rule_id = engine.check("Kaptn", "All tests pass. Should I proceed?")
        assert reply == "yes"
        assert rule_id == "proceed"

    def test_no_match_returns_none(self):
        engine = self._make_engine()
        reply, rule_id = engine.check("Kaptn", "Here is the code I wrote.")
        assert reply is None
        assert rule_id is None

    def test_first_match_wins(self):
        rules = [
            AutoReplyRule(id="first", pattern="should I proceed", reply="first-reply"),
            AutoReplyRule(id="second", pattern="should I proceed", reply="second-reply"),
        ]
        engine = self._make_engine(rules=rules)
        reply, rule_id = engine.check("Kaptn", "Should I proceed?")
        assert reply == "first-reply"
        assert rule_id == "first"

    def test_empty_text_returns_none(self):
        engine = self._make_engine()
        reply, rule_id = engine.check("Kaptn", "")
        assert reply is None

    def test_cooldown_blocks_rapid_replies(self):
        engine = self._make_engine(cooldown=10.0)
        reply1, _ = engine.check("Kaptn", "Should I proceed?")
        assert reply1 == "yes"

        # Same window, different text, within cooldown
        reply2, _ = engine.check("Kaptn", "Shall I continue with the next step?")
        assert reply2 is None

    def test_cooldown_per_window(self):
        engine = self._make_engine(cooldown=10.0)
        reply1, _ = engine.check("Kaptn", "Should I proceed?")
        assert reply1 == "yes"

        # Different window — not on cooldown
        reply2, _ = engine.check("OtherWindow", "Should I proceed?")
        assert reply2 == "yes"

    def test_duplicate_text_skipped(self):
        engine = self._make_engine()
        reply1, _ = engine.check("Kaptn", "Should I proceed?")
        assert reply1 == "yes"

        # Same exact text again — already checked
        reply2, _ = engine.check("Kaptn", "Should I proceed?")
        assert reply2 is None

    def test_consecutive_limit_pauses(self):
        engine = self._make_engine(max_consecutive=2)
        reply1, _ = engine.check("Kaptn", "Should I proceed? (1)")
        assert reply1 == "yes"

        reply2, _ = engine.check("Kaptn", "Should I proceed? (2)")
        assert reply2 == "yes"

        # Third consecutive — exceeds limit, paused
        reply3, _ = engine.check("Kaptn", "Should I proceed? (3)")
        assert reply3 is None
        assert "Kaptn" in engine.paused_windows

    def test_reset_consecutive_allows_more(self):
        engine = self._make_engine(max_consecutive=2)
        engine.check("Kaptn", "Should I proceed? (1)")
        engine.check("Kaptn", "Should I proceed? (2)")

        # Reset counter (simulates user sending a message)
        engine.reset_consecutive("Kaptn")

        reply, _ = engine.check("Kaptn", "Should I proceed? (3)")
        assert reply == "yes"

    def test_resume_window(self):
        engine = self._make_engine(max_consecutive=1)
        engine.check("Kaptn", "Should I proceed?")
        engine.check("Kaptn", "Should I proceed? again")
        assert "Kaptn" in engine.paused_windows

        engine.resume_window("Kaptn")
        assert "Kaptn" not in engine.paused_windows

        reply, _ = engine.check("Kaptn", "Should I proceed? after resume")
        assert reply == "yes"

    def test_resume_all(self):
        engine = self._make_engine(max_consecutive=1)
        engine.check("W1", "Should I proceed?")
        engine.check("W1", "Should I proceed? again")
        engine.check("W2", "Should I proceed?")
        engine.check("W2", "Should I proceed? again")
        assert len(engine.paused_windows) == 2

        engine.resume_all()
        assert len(engine.paused_windows) == 0

    def test_paused_window_returns_none(self):
        engine = self._make_engine()
        engine._paused_windows.add("Kaptn")
        reply, _ = engine.check("Kaptn", "Should I proceed?")
        assert reply is None

    def test_pipe_alternatives_match(self):
        engine = self._make_engine()
        reply, rule_id = engine.check("Kaptn", "Do you want me to continue?")
        assert reply == "yes, continue"
        assert rule_id == "continue"

    def test_get_status(self):
        engine = self._make_engine()
        status = engine.get_status()
        assert "rules" in status
        assert len(status["rules"]) == 2
        assert status["cooldown_seconds"] == 0.0
        assert status["max_consecutive"] == 5


class TestDefaultRules:
    """Verify the built-in default rules match expected patterns."""

    def test_defaults_loaded(self):
        engine = AutoReplyEngine()
        assert len(engine.rules) == len(DEFAULT_AUTO_REPLY_RULES)

    def test_proceed_default(self):
        engine = AutoReplyEngine(cooldown_seconds=0)
        reply, rule_id = engine.check("W", "All done. Should I proceed?")
        assert reply == "yes"
        assert rule_id == "proceed-yes"

    def test_continue_default(self):
        engine = AutoReplyEngine(cooldown_seconds=0)
        reply, rule_id = engine.check("W", "Shall I continue with the implementation?")
        assert reply == "yes, continue"
        assert rule_id == "continue-yes"

    def test_commit_default(self):
        engine = AutoReplyEngine(cooldown_seconds=0)
        reply, rule_id = engine.check("W", "Ready to commit?")
        assert reply == "yes"
        assert rule_id == "commit-yes"

    def test_discuss_default(self):
        engine = AutoReplyEngine(cooldown_seconds=0)
        reply, rule_id = engine.check("W", "Want to discuss the approach first?")
        assert reply == "no, just implement it"
        assert rule_id == "discuss-yes"

    def test_no_match_on_random_text(self):
        engine = AutoReplyEngine(cooldown_seconds=0)
        reply, _ = engine.check("W", "Here is the refactored code with improved error handling.")
        assert reply is None
