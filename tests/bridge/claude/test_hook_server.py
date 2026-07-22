"""Tests for the Claude hook HTTP server — real requests over localhost."""

import json
import urllib.error
import urllib.request

import pytest

from bridge.audit.audit_logger import AuditLogger
from bridge.autopilot.auto_pilot_engine import AutoPilotEngine
from bridge.autopilot.loop_detector import LoopDetector
from bridge.autopilot.rule_evaluator import RuleEvaluator
from bridge.claude.claude_adapter import ClaudeAdapter
from bridge.claude.hook_server import ClaudeHookServer

RULES = [{"id": "allow-reads", "category": "file_read", "action": "approve"}]


@pytest.fixture
def server():
    autopilot = AutoPilotEngine(
        rule_evaluator=RuleEvaluator(RULES), loop_detector=LoopDetector()
    )
    audit = AuditLogger(db_path=":memory:")
    adapter = ClaudeAdapter(autopilot, audit)
    srv = ClaudeHookServer(adapter, port=0)  # OS-assigned port
    srv.start()
    yield srv
    srv.stop()
    audit.close()


def post(server, path, payload, raw=None):
    request = urllib.request.Request(
        f"http://127.0.0.1:{server.port}{path}",
        data=raw if raw is not None else json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.status, json.loads(response.read())


def test_hook_decision_roundtrip(server):
    status, body = post(server, "/hook", {
        "session_id": "s1", "cwd": "/tmp/proj", "hook_event_name": "PreToolUse",
        "tool_name": "Read", "tool_input": {"file_path": "/tmp/a.py"},
    })
    assert status == 200
    assert body["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_non_pretooluse_returns_empty(server):
    status, body = post(server, "/hook", {"hook_event_name": "Stop"})
    assert status == 200
    assert body == {}


def test_invalid_json_400(server):
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        post(server, "/hook", None, raw=b"{not json")
    assert exc_info.value.code == 400


def test_unknown_path_404(server):
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        post(server, "/other", {})
    assert exc_info.value.code == 404


def test_health_endpoint(server):
    with urllib.request.urlopen(f"http://127.0.0.1:{server.port}/health", timeout=5) as response:
        assert response.status == 200
        assert json.loads(response.read()) == {"status": "ok"}


def test_get_unknown_path_404(server):
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(f"http://127.0.0.1:{server.port}/nope", timeout=5)
    assert exc_info.value.code == 404


def test_status_endpoint(server):
    with urllib.request.urlopen(f"http://127.0.0.1:{server.port}/status", timeout=5) as response:
        body = json.loads(response.read())
    assert body["autopilot_enabled"] is True
    assert body["rules_loaded"] == 1
    assert "limit_status" in body


def test_reset_endpoint(server):
    status, body = post(server, "/reset", {})
    assert status == 200
    assert body == {"status": "reset"}


def test_adapter_exception_500(server):
    def boom(event):
        raise RuntimeError("boom")

    server.adapter.handle_hook_event = boom
    # The handler holds a reference to the same adapter object
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        post(server, "/hook", {"hook_event_name": "PreToolUse", "tool_name": "Read"})
    assert exc_info.value.code == 500


def test_running_and_stop_lifecycle():
    autopilot = AutoPilotEngine(
        rule_evaluator=RuleEvaluator(RULES), loop_detector=LoopDetector()
    )
    audit = AuditLogger(db_path=":memory:")
    srv = ClaudeHookServer(ClaudeAdapter(autopilot, audit), port=0)
    assert not srv.running
    srv.start()
    assert srv.running
    assert srv.port != 0
    srv.stop()
    assert not srv.running
    audit.close()
