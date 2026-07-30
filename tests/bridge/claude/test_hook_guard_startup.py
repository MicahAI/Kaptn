"""The startup self-check gates the hook server itself.

A governor whose own PreToolUse hook is async or under-margined enforces
nothing, so it must refuse to serve rather than look healthy while gating
nothing (ADR-0012). Refusing degrades to Claude Code's own permission
prompts — fail-open toward a human, not toward silent execution.
"""

import json
from unittest.mock import patch

from bridge.main import KaptnBridge

KAPTN_COMMAND = '"/venv/bin/python" -m bridge.claude.hook_client --port 3002'


def _config(**claude):
    return {
        "cdp_port": 9222,
        "audit_db": ":memory:",
        "autopilot": {"enabled": True, "rules": [], "loop_detection": {}},
        "claude": {"enabled": True, **claude},
    }


def _bridge(**claude):
    with patch("bridge.main.CdpDiscovery"):
        return KaptnBridge(_config(**claude))


def _settings_file(tmp_path, hook: dict):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"hooks": {"PreToolUse": [
        {"matcher": "*", "hooks": [hook]},
    ]}}))
    return path


def _run(bridge, sources):
    """Run the self-check against an explicit source list."""
    real = bridge.hook_guard_self_check

    def check():
        with patch("bridge.claude.hook_guard.effective_settings_sources",
                   return_value=sources):
            return real()

    return check()


class TestStartupSelfCheck:
    def test_sound_config_serves(self, tmp_path):
        path = _settings_file(tmp_path, {
            "type": "command", "command": KAPTN_COMMAND, "timeout": 10,
        })
        assert _run(_bridge(), [path]) is True

    def test_own_async_hook_refuses_to_serve(self, tmp_path):
        path = _settings_file(tmp_path, {
            "type": "command", "command": KAPTN_COMMAND, "timeout": 10, "async": True,
        })
        assert _run(_bridge(), [path]) is False

    def test_own_under_margined_hook_refuses_to_serve(self, tmp_path):
        path = _settings_file(tmp_path, {
            "type": "command", "command": KAPTN_COMMAND, "timeout": 4,
        })
        assert _run(_bridge(), [path]) is False

    def test_margin_follows_the_configured_answer_budget(self, tmp_path):
        path = _settings_file(tmp_path, {
            "type": "command", "command": KAPTN_COMMAND, "timeout": 10,
        })
        assert _run(_bridge(answer_budget_seconds=30), [path]) is False
        assert _run(_bridge(answer_budget_seconds=5), [path]) is True

    def test_third_party_problem_does_not_stop_the_server(self, tmp_path):
        path = tmp_path / "settings.json"
        path.write_text(json.dumps({"hooks": {"PreToolUse": [
            {"matcher": "*", "hooks": [
                {"type": "command", "command": KAPTN_COMMAND, "timeout": 10},
            ]},
            {"matcher": "*", "hooks": [
                {"type": "command", "command": "other-governor", "async": True},
            ]},
        ]}}))
        assert _run(_bridge(), [path]) is True

    def test_hook_server_is_dropped_when_the_check_fails(self):
        bridge = _bridge()
        assert bridge.hook_server is not None
        with patch.object(bridge, "hook_guard_self_check", return_value=False):
            assert bridge._start_hook_server() is False
        assert bridge.hook_server is None
