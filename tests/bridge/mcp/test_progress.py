"""Tests for bridge/mcp/_progress.py — atomic JSON file helpers."""

import json
import os
import time

from bridge.mcp import _progress


class TestProgress:

    def test_write_and_read_progress(self, setup_mcp_test_env):
        data = {"running": True, "pid": 12345, "windows": ["Kaptn"]}
        _progress.write_progress(data)
        result = _progress.read_progress()
        assert result["running"] is True
        assert result["pid"] == 12345
        assert result["windows"] == ["Kaptn"]

    def test_write_and_read_commands(self, setup_mcp_test_env):
        data = {"temp_rules": [{"action": "create_watch", "window": "Kaptn"}]}
        _progress.write_commands(data)
        result = _progress.read_commands()
        assert len(result["temp_rules"]) == 1
        assert result["temp_rules"][0]["action"] == "create_watch"

    def test_read_missing_file_returns_empty(self, setup_mcp_test_env):
        _progress.clear_progress()
        assert _progress.read_progress() == {}
        assert _progress.read_commands() == {}

    def test_clear_progress(self, setup_mcp_test_env):
        _progress.write_progress({"running": True})
        _progress.clear_progress()
        assert _progress.read_progress() == {}

    def test_clear_commands(self, setup_mcp_test_env):
        _progress.write_commands({"temp_rules": []})
        _progress.clear_commands()
        assert _progress.read_commands() == {}

    def test_is_bridge_running_true(self, setup_mcp_test_env):
        _progress.write_progress({
            "running": True,
            "pid": os.getpid(),  # Current process is alive
        })
        assert _progress.is_bridge_running() is True

    def test_is_bridge_running_false_no_file(self, setup_mcp_test_env):
        _progress.clear_progress()
        assert _progress.is_bridge_running() is False

    def test_is_bridge_running_false_not_running(self, setup_mcp_test_env):
        _progress.write_progress({"running": False, "pid": os.getpid()})
        assert _progress.is_bridge_running() is False

    def test_is_bridge_running_stale_pid(self, setup_mcp_test_env):
        _progress.write_progress({"running": True, "pid": 99999999})
        assert _progress.is_bridge_running() is False

    def test_atomic_write_is_complete(self, setup_mcp_test_env):
        """Verify file contents are always valid JSON (no partial writes)."""
        for i in range(50):
            _progress.write_progress({"running": True, "counter": i})
            data = _progress.read_progress()
            assert data["counter"] == i

    def test_read_corrupt_file_returns_empty(self, setup_mcp_test_env):
        with open(_progress.PROGRESS_FILE, "w") as f:
            f.write("{corrupt json!!")
        assert _progress.read_progress() == {}
