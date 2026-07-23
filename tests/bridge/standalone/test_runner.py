"""Tests for the daemonless runner — persistence across invocations."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from bridge.standalone import runner

PLUGIN_ROOT = Path(__file__).resolve().parents[3]

CONFIG = {
    "audit_db": "kaptn_audit.db",
    "autopilot": {
        "enabled": True,
        "rules": [
            {"id": "allow-reads", "category": "file_read", "action": "approve"},
            {"id": "allow-writes", "category": "file_write", "action": "approve",
             "limits": {"max_per_session": 2}},
            {"id": "allow-safe", "category": "command_safe", "action": "approve"},
        ],
        "loop_detection": {"enabled": True, "same_action_threshold": 3},
    },
}


@pytest.fixture
def state_dir(tmp_path):
    (tmp_path / "kaptn.config.json").write_text(json.dumps(CONFIG))
    return tmp_path


def make_event(tool_name="Read", tool_input=None, session="sess-1"):
    return {
        "session_id": session,
        "cwd": "/tmp/proj",
        "hook_event_name": "PreToolUse",
        "tool_name": tool_name,
        "tool_input": tool_input if tool_input is not None else {"file_path": "/tmp/a.py"},
    }


def decision(result):
    return result["hookSpecificOutput"]["permissionDecision"]


class TestHandleEvent:
    def test_basic_allow(self, state_dir):
        result = runner.handle_event(make_event(), state_dir=state_dir)
        assert decision(result) == "allow"

    def test_non_pretooluse_none(self, state_dir):
        event = make_event()
        event["hook_event_name"] = "Stop"
        assert runner.handle_event(event, state_dir=state_dir) is None

    def test_limits_persist_across_invocations(self, state_dir):
        for path in ("/a.py", "/b.py"):
            result = runner.handle_event(
                make_event("Write", {"file_path": path}), state_dir=state_dir
            )
            assert decision(result) == "allow"
        # Third write in the same session — separate process in real life,
        # separate handle_event call here — must hit the persisted cap
        result = runner.handle_event(
            make_event("Write", {"file_path": "/c.py"}), state_dir=state_dir
        )
        assert decision(result) == "ask"
        assert "limit_exceeded" in result["hookSpecificOutput"]["permissionDecisionReason"]

    def test_limits_per_session(self, state_dir):
        for path in ("/a.py", "/b.py"):
            runner.handle_event(
                make_event("Write", {"file_path": path}, session="A"), state_dir=state_dir
            )
        result = runner.handle_event(
            make_event("Write", {"file_path": "/c.py"}, session="B"), state_dir=state_dir
        )
        assert decision(result) == "allow"

    def test_loop_detection_persists(self, state_dir):
        event = make_event("Bash", {"command": "cat same.txt"})
        assert decision(runner.handle_event(event, state_dir=state_dir)) == "allow"
        assert decision(runner.handle_event(event, state_dir=state_dir)) == "allow"
        result = runner.handle_event(event, state_dir=state_dir)
        assert decision(result) == "deny"
        assert "loop_detected" in result["hookSpecificOutput"]["permissionDecisionReason"]

    def test_audit_persisted(self, state_dir):
        runner.handle_event(make_event(), state_dir=state_dir)
        runner.handle_event(make_event(), state_dir=state_dir)
        from bridge.audit.audit_logger import AuditLogger
        audit = AuditLogger(db_path=str(state_dir / "kaptn_audit.db"))
        try:
            assert audit.get_count() == 2
        finally:
            audit.close()

    def test_reset_state_clears_caps(self, state_dir):
        for path in ("/a.py", "/b.py", "/c.py"):
            runner.handle_event(
                make_event("Write", {"file_path": path}), state_dir=state_dir
            )
        runner.reset_state(state_dir=state_dir)
        result = runner.handle_event(
            make_event("Write", {"file_path": "/d.py"}), state_dir=state_dir
        )
        assert decision(result) == "allow"


class TestHookScript:
    """End-to-end through the actual executable, as Claude Code runs it."""

    def run_hook(self, event, state_dir):
        return subprocess.run(
            [sys.executable, str(PLUGIN_ROOT / "scripts" / "kaptn-hook")],
            input=json.dumps(event),
            capture_output=True, text=True, timeout=30,
            env={"PATH": "/usr/bin:/bin",
                 "KAPTN_CONFIG": str(state_dir / "kaptn.config.json"),
                 "HOME": str(state_dir)},
        )

    def test_script_allow_roundtrip(self, state_dir):
        proc = self.run_hook(make_event(), state_dir)
        assert proc.returncode == 0
        assert decision(json.loads(proc.stdout)) == "allow"

    def test_script_fails_open_on_garbage(self, state_dir):
        proc = subprocess.run(
            [sys.executable, str(PLUGIN_ROOT / "scripts" / "kaptn-hook")],
            input="{not json", capture_output=True, text=True, timeout=30,
        )
        assert proc.returncode == 0
        assert proc.stdout == ""
