"""Tests for AutoReplyRule — pattern matching for conversational stalls."""


from bridge.autopilot.auto_reply_rule import AutoReplyRule


class TestAutoReplyRule:
    """Tests for AutoReplyRule.matches()."""

    def test_simple_end_match(self):
        rule = AutoReplyRule(id="test", pattern="should I proceed", reply="yes")
        assert rule.matches("All tests pass. Should I proceed?")

    def test_end_match_only_checks_tail(self):
        rule = AutoReplyRule(id="test", pattern="should I proceed", reply="yes")
        # Pattern in the middle, not near the end — should still match within tail
        text = "Should I proceed with the refactoring? " + ("x" * 300)
        assert not rule.matches(text)

    def test_anywhere_match(self):
        rule = AutoReplyRule(id="test", pattern="should I proceed", reply="yes", match="anywhere")
        text = "Should I proceed with the refactoring? " + ("x" * 300)
        assert rule.matches(text)

    def test_case_insensitive(self):
        rule = AutoReplyRule(id="test", pattern="should i proceed", reply="yes")
        assert rule.matches("SHOULD I PROCEED?")

    def test_pipe_alternatives(self):
        rule = AutoReplyRule(id="test", pattern="shall I continue|want me to continue", reply="yes")
        assert rule.matches("Shall I continue with the next step?")
        assert rule.matches("Do you want me to continue?")
        assert not rule.matches("I continued with the task.")

    def test_disabled_rule_no_match(self):
        rule = AutoReplyRule(id="test", pattern="should I proceed", reply="yes", enabled=False)
        assert not rule.matches("Should I proceed?")

    def test_empty_text_no_match(self):
        rule = AutoReplyRule(id="test", pattern="should I proceed", reply="yes")
        assert not rule.matches("")
        assert not rule.matches(None)

    def test_empty_pattern_no_match(self):
        rule = AutoReplyRule(id="test", pattern="", reply="yes")
        assert not rule.matches("Should I proceed?")

    def test_from_dict(self):
        data = {
            "id": "proceed-yes",
            "pattern": "should I proceed",
            "reply": "yes",
            "match": "end",
            "enabled": True,
        }
        rule = AutoReplyRule.from_dict(data)
        assert rule.id == "proceed-yes"
        assert rule.pattern == "should I proceed"
        assert rule.reply == "yes"
        assert rule.match == "end"
        assert rule.enabled is True

    def test_from_dict_defaults(self):
        data = {"id": "test", "pattern": "continue", "reply": "yes"}
        rule = AutoReplyRule.from_dict(data)
        assert rule.match == "end"
        assert rule.enabled is True

    def test_long_message_end_match(self):
        """Pattern near end of a long message should match."""
        rule = AutoReplyRule(id="test", pattern="should I proceed", reply="yes")
        text = ("Here is a very long explanation. " * 20) + "Should I proceed?"
        assert rule.matches(text)
