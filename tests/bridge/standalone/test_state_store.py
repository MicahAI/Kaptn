"""Tests for the SQLite state store used in daemonless mode."""

import pytest

from bridge.standalone.state_store import StateStore


@pytest.fixture
def store(tmp_path):
    s = StateStore(tmp_path / "state.db")
    yield s
    s.close()


class TestCounters:
    def test_increment_and_get(self, store):
        assert store.get_count("s1", "rule-a") == 0
        store.increment("s1", "rule-a")
        store.increment("s1", "rule-a")
        assert store.get_count("s1", "rule-a") == 2

    def test_scopes_isolated(self, store):
        store.increment("s1", "rule-a")
        assert store.get_count("s2", "rule-a") == 0

    def test_consecutive_tracking(self, store):
        store.increment("s1", "rule-a")
        store.increment("s1", "rule-a")
        assert store.consecutive_for("s1", "rule-a") == 2
        store.increment("s1", "rule-b")  # breaks the streak
        assert store.consecutive_for("s1", "rule-a") == 0
        assert store.consecutive_for("s1", "rule-b") == 1

    def test_minute_count_prunes_old(self, store):
        store.increment("s1", "rule-a", now=1000.0)
        store.increment("s1", "rule-a", now=1030.0)
        assert store.minute_count("s1", "rule-a", now=1050.0) == 2
        assert store.minute_count("s1", "rule-a", now=1085.0) == 1  # 1000 aged out
        assert store.minute_count("s1", "rule-a", now=1200.0) == 0  # all aged out

    def test_snapshot(self, store):
        store.increment("s1", "rule-a")
        store.increment("s2", "rule-a")
        assert store.counters_snapshot() == {("s1", "rule-a"): 1, ("s2", "rule-a"): 1}

    def test_reset_all(self, store):
        store.increment("s1", "rule-a")
        store.add_paused("w1")
        store.set_history("s1", ["k1"])
        store.reset_all()
        assert store.get_count("s1", "rule-a") == 0
        assert store.get_paused() == set()
        assert store.get_history("s1") == []

    def test_reset_rule(self, store):
        store.increment("s1", "rule-a")
        store.increment("s1", "rule-b")
        store.reset_rule("rule-a")
        assert store.get_count("s1", "rule-a") == 0
        assert store.get_count("s1", "rule-b") == 1


class TestHistoryAndPauses:
    def test_history_roundtrip_ordered(self, store):
        store.set_history("s1", ["k1", "k2", "k3"])
        assert store.get_history("s1") == ["k1", "k2", "k3"]

    def test_history_trimmed_to_limit(self, store):
        store.set_history("s1", [f"k{i}" for i in range(30)], limit=20)
        history = store.get_history("s1", limit=20)
        assert len(history) == 20
        assert history[-1] == "k29"

    def test_history_per_scope(self, store):
        store.set_history("s1", ["a"])
        store.set_history("s2", ["b"])
        assert store.get_history("s1") == ["a"]
        assert store.get_history("s2") == ["b"]

    def test_paused_windows(self, store):
        store.add_paused("w1")
        store.add_paused("w1")  # idempotent
        store.add_paused("w2")
        assert store.get_paused() == {"w1", "w2"}
