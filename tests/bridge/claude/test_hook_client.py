"""Tests for the hook client — stdin → HTTP → stdout, failing open."""

import io
import json

import pytest

from bridge.audit.audit_logger import AuditLogger
from bridge.autopilot.auto_pilot_engine import AutoPilotEngine
from bridge.autopilot.loop_detector import LoopDetector
from bridge.autopilot.rule_evaluator import RuleEvaluator
from bridge.claude import hook_client
from bridge.claude.claude_adapter import ClaudeAdapter
from bridge.claude.hook_server import ClaudeHookServer

RULES = [
    {"id": "allow-reads", "category": "file_read", "action": "approve"},
    {"id": "block-deletes", "category": "file_delete", "action": "deny"},
]

EVENT = {
    "session_id": "s1", "cwd": "/tmp/proj", "hook_event_name": "PreToolUse",
    "tool_name": "Read", "tool_input": {"file_path": "/tmp/a.py"},
}


@pytest.fixture
def server():
    autopilot = AutoPilotEngine(
        rule_evaluator=RuleEvaluator(RULES), loop_detector=LoopDetector()
    )
    audit = AuditLogger(db_path=":memory:")
    srv = ClaudeHookServer(ClaudeAdapter(autopilot, audit), port=0)
    srv.start()
    yield srv
    srv.stop()
    audit.close()


def run_client(monkeypatch, capsys, stdin_text, argv):
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin_text))
    code = hook_client.main(argv)
    return code, capsys.readouterr().out


def test_allow_decision_printed(server, monkeypatch, capsys):
    code, out = run_client(
        monkeypatch, capsys, json.dumps(EVENT), ["--port", str(server.port)]
    )
    assert code == 0
    decision = json.loads(out)
    assert decision["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_deny_decision_printed(server, monkeypatch, capsys):
    event = dict(EVENT, tool_name="Bash", tool_input={"command": "rm -rf x"})
    code, out = run_client(
        monkeypatch, capsys, json.dumps(event), ["--port", str(server.port)]
    )
    assert code == 0
    assert json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_non_pretooluse_prints_nothing(server, monkeypatch, capsys):
    event = dict(EVENT, hook_event_name="Stop")
    code, out = run_client(
        monkeypatch, capsys, json.dumps(event), ["--port", str(server.port)]
    )
    assert code == 0
    assert out == ""


def test_fails_open_when_server_down(monkeypatch, capsys):
    # Port 1 is never listening — connection refused
    code, out = run_client(
        monkeypatch, capsys, json.dumps(EVENT), ["--port", "1", "--timeout", "1"]
    )
    assert code == 0
    assert out == ""


def test_fails_open_on_bad_stdin(server, monkeypatch, capsys):
    code, out = run_client(
        monkeypatch, capsys, "{not json", ["--port", str(server.port)]
    )
    assert code == 0
    assert out == ""


def test_empty_stdin_treated_as_empty_event(server, monkeypatch, capsys):
    code, out = run_client(monkeypatch, capsys, "", ["--port", str(server.port)])
    assert code == 0
    assert out == ""  # empty event → non-PreToolUse → {} → nothing printed


def test_fails_open_on_invalid_response_body(monkeypatch, capsys):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b"{not json"

    monkeypatch.setattr(
        "urllib.request.urlopen", lambda *args, **kwargs: FakeResponse()
    )
    code, out = run_client(monkeypatch, capsys, json.dumps(EVENT), ["--port", "3002"])
    assert code == 0
    assert out == ""


def test_entry_exits_zero(server, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(EVENT)))
    monkeypatch.setattr("sys.argv", ["kaptn-claude-hook", "--port", str(server.port)])
    with pytest.raises(SystemExit) as exc_info:
        hook_client.entry()
    assert exc_info.value.code == 0
