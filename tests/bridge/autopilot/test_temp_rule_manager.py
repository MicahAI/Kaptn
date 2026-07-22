"""Tests for TempRuleManager — temporary rules with TTL."""

import time

import pytest

from bridge.autopilot.temp_rule_manager import (
    MAX_CONCURRENT_RULES,
    MAX_TTL_MINUTES,
    TempRule,
    TempRuleManager,
)


class TestTempRule:
    """Tests for the TempRule dataclass."""

    def test_not_expired_when_future(self):
        rule = TempRule(expires_at=time.time() + 3600)
        assert not rule.expired

    def test_expired_when_past(self):
        rule = TempRule(expires_at=time.time() - 1)
        assert rule.expired

    def test_expired_when_count_exceeded(self):
        rule = TempRule(expires_at=time.time() + 3600, max_count=5, approved_count=5)
        assert rule.expired

    def test_not_expired_when_count_below(self):
        rule = TempRule(expires_at=time.time() + 3600, max_count=5, approved_count=3)
        assert not rule.expired

    def test_unlimited_count(self):
        rule = TempRule(expires_at=time.time() + 3600, max_count=None, approved_count=999)
        assert not rule.expired

    def test_minutes_remaining(self):
        rule = TempRule(expires_at=time.time() + 600)  # 10 min
        assert 9.9 < rule.minutes_remaining < 10.1

    def test_minutes_remaining_zero_when_expired(self):
        rule = TempRule(expires_at=time.time() - 60)
        assert rule.minutes_remaining == 0.0

    def test_to_dict(self):
        rule = TempRule(
            category="command_unsafe",
            action="approve",
            window="Kaptn",
            expires_at=time.time() + 1200,
            max_count=10,
            approved_count=3,
        )
        d = rule.to_dict()
        assert d["category"] == "command_unsafe"
        assert d["action"] == "approve"
        assert d["window"] == "Kaptn"
        assert d["approved_count"] == 3
        assert d["max_count"] == 10
        assert d["expires_in_minutes"] > 0

    def test_id_auto_generated(self):
        r1 = TempRule()
        r2 = TempRule()
        assert r1.id != r2.id
        assert r1.id.startswith("tmp-")


class TestTempRuleManager:
    """Tests for TempRuleManager CRUD operations."""

    def test_create_rule(self):
        mgr = TempRuleManager()
        rule = mgr.create_rule(category="command_unsafe", minutes=10)
        assert rule.category == "command_unsafe"
        assert rule.action == "approve"
        assert not rule.expired
        assert mgr.count == 1

    def test_create_rule_with_window(self):
        mgr = TempRuleManager()
        rule = mgr.create_rule(category="file_write", minutes=5, window="Kaptn")
        assert rule.window == "Kaptn"

    def test_create_rule_with_max_count(self):
        mgr = TempRuleManager()
        rule = mgr.create_rule(category="command_safe", minutes=5, max_count=3)
        assert rule.max_count == 3

    def test_create_rule_caps_ttl(self):
        mgr = TempRuleManager()
        rule = mgr.create_rule(category="command_safe", minutes=9999)
        max_expires = time.time() + (MAX_TTL_MINUTES * 60) + 5
        assert rule.expires_at <= max_expires

    def test_create_rule_rejects_excluded_category(self):
        mgr = TempRuleManager()
        with pytest.raises(ValueError, match="excluded"):
            mgr.create_rule(category="file_delete", minutes=10)

    def test_create_rule_rejects_zero_minutes(self):
        mgr = TempRuleManager()
        with pytest.raises(ValueError, match="at least 1 minute"):
            mgr.create_rule(category="command_safe", minutes=0)

    def test_create_rule_rejects_when_max_concurrent(self):
        mgr = TempRuleManager()
        for i in range(MAX_CONCURRENT_RULES):
            mgr.create_rule(category="command_safe", minutes=10)
        with pytest.raises(ValueError, match="Max concurrent"):
            mgr.create_rule(category="command_safe", minutes=10)

    def test_cancel_rule(self):
        mgr = TempRuleManager()
        rule = mgr.create_rule(category="command_safe", minutes=10)
        cancelled = mgr.cancel_rule(rule.id)
        assert cancelled is not None
        assert cancelled.id == rule.id
        assert mgr.count == 0

    def test_cancel_rule_not_found(self):
        mgr = TempRuleManager()
        assert mgr.cancel_rule("nonexistent") is None

    def test_cancel_window(self):
        mgr = TempRuleManager()
        mgr.create_rule(category="command_safe", minutes=10, window="Kaptn")
        mgr.create_rule(category="file_write", minutes=10, window="Kaptn")
        mgr.create_rule(category="search", minutes=10, window="Other")
        cancelled = mgr.cancel_window("Kaptn")
        assert len(cancelled) == 2
        assert mgr.count == 1

    def test_cancel_all(self):
        mgr = TempRuleManager()
        mgr.create_rule(category="command_safe", minutes=10)
        mgr.create_rule(category="file_write", minutes=10)
        cancelled = mgr.cancel_all()
        assert len(cancelled) == 2
        assert mgr.count == 0

    def test_get_rule(self):
        mgr = TempRuleManager()
        rule = mgr.create_rule(category="command_safe", minutes=10)
        found = mgr.get_rule(rule.id)
        assert found is not None
        assert found.id == rule.id

    def test_get_rule_returns_none_for_expired(self):
        mgr = TempRuleManager()
        rule = mgr.create_rule(category="command_safe", minutes=10)
        rule.expires_at = time.time() - 1  # force expire
        assert mgr.get_rule(rule.id) is None

    def test_get_active_rules_newest_first(self):
        mgr = TempRuleManager()
        r1 = mgr.create_rule(category="command_safe", minutes=10)
        r1.created_at = 100.0
        r2 = mgr.create_rule(category="file_write", minutes=10)
        r2.created_at = 200.0
        active = mgr.get_active_rules()
        assert active[0].id == r2.id
        assert active[1].id == r1.id

    def test_get_active_rules_filters_by_window(self):
        mgr = TempRuleManager()
        mgr.create_rule(category="command_safe", minutes=10, window="Kaptn")
        mgr.create_rule(category="file_write", minutes=10, window="Other")
        mgr.create_rule(category="search", minutes=10)  # all windows
        active = mgr.get_active_rules(window="Kaptn")
        assert len(active) == 2  # Kaptn-specific + all-windows

    def test_match_returns_newest(self):
        mgr = TempRuleManager()
        r1 = mgr.create_rule(category="command_safe", minutes=10)
        r1.created_at = 100.0
        r2 = mgr.create_rule(category="command_safe", minutes=20)
        r2.created_at = 200.0
        matched = mgr.match("command_safe")
        assert matched.id == r2.id

    def test_match_respects_window(self):
        mgr = TempRuleManager()
        mgr.create_rule(category="command_safe", minutes=10, window="Kaptn")
        mgr.create_rule(category="command_safe", minutes=10, window="Other")
        assert mgr.match("command_safe", window="Kaptn") is not None
        assert mgr.match("command_safe", window="Kaptn").window == "Kaptn"

    def test_match_returns_none_when_no_match(self):
        mgr = TempRuleManager()
        mgr.create_rule(category="command_safe", minutes=10)
        assert mgr.match("file_delete") is None

    def test_match_wildcard_category(self):
        mgr = TempRuleManager()
        mgr.create_rule(category="*", minutes=10)
        assert mgr.match("command_safe") is not None
        assert mgr.match("file_write") is not None

    def test_record_approval(self):
        mgr = TempRuleManager()
        rule = mgr.create_rule(category="command_safe", minutes=10, max_count=3)
        mgr.record_approval(rule.id)
        assert rule.approved_count == 1
        mgr.record_approval(rule.id)
        assert rule.approved_count == 2

    def test_record_approval_exhausts_rule(self):
        mgr = TempRuleManager()
        rule = mgr.create_rule(category="command_safe", minutes=10, max_count=2)
        mgr.record_approval(rule.id)
        mgr.record_approval(rule.id)
        assert mgr.count == 0  # rule auto-removed

    def test_cleanup_expired(self):
        mgr = TempRuleManager()
        r1 = mgr.create_rule(category="command_safe", minutes=10)
        r2 = mgr.create_rule(category="file_write", minutes=10)
        r1.expires_at = time.time() - 1  # force expire
        assert mgr.count == 1  # cleanup happens on access
        assert mgr.get_rule(r2.id) is not None

    def test_create_watch(self):
        mgr = TempRuleManager()
        rules = mgr.create_watch(window="Kaptn", minutes=20)
        assert len(rules) == 6  # default categories minus excluded
        for rule in rules:
            assert rule.window == "Kaptn"
            assert rule.action == "approve"

    def test_create_watch_custom_categories(self):
        mgr = TempRuleManager()
        rules = mgr.create_watch(
            window="Kaptn", minutes=10,
            categories=["command_safe", "file_read"],
        )
        assert len(rules) == 2

    def test_create_watch_skips_excluded(self):
        mgr = TempRuleManager()
        rules = mgr.create_watch(
            window="Kaptn", minutes=10,
            categories=["command_safe", "file_delete"],
        )
        assert len(rules) == 1
        assert rules[0].category == "command_safe"

    def test_status(self):
        mgr = TempRuleManager()
        mgr.create_rule(category="command_safe", minutes=10, window="Kaptn")
        mgr.create_rule(category="file_write", minutes=10)
        status = mgr.status()
        assert status["active_rules"] == 2
        assert status["max_rules"] == MAX_CONCURRENT_RULES
        assert "Kaptn" in status["windows"]
        assert "__all__" in status["windows"]
