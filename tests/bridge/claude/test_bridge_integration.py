"""Integration tests — KaptnBridge running the Claude hook server without CDP."""

import json
import urllib.request

from bridge.main import KaptnBridge


def make_config(tmp_path, claude_enabled=True):
    return {
        "cdp_port": 1,  # nothing listening — CDP unavailable
        "audit_db": str(tmp_path / "audit.db"),
        "claude": {"enabled": claude_enabled, "hook_port": 0},
        "autopilot": {
            "enabled": True,
            "rules": [{"id": "allow-reads", "category": "file_read", "action": "approve"}],
        },
    }


def test_bridge_builds_hook_server_when_enabled(tmp_path):
    bridge = KaptnBridge(make_config(tmp_path))
    assert bridge.hook_server is not None
    bridge.audit.close()


def test_bridge_skips_hook_server_when_disabled(tmp_path):
    bridge = KaptnBridge(make_config(tmp_path, claude_enabled=False))
    assert bridge.hook_server is None
    bridge.audit.close()


async def test_bridge_serves_hooks_without_cdp(tmp_path):
    """With CDP down but Claude enabled, the bridge must still serve decisions."""
    bridge = KaptnBridge(make_config(tmp_path))

    claude_active = bridge._start_hook_server()
    assert claude_active is True
    cdp_ok = await bridge._connect_cdp()
    assert cdp_ok is False

    # A hook decision flows end-to-end through the running server
    event = {
        "session_id": "s1", "cwd": str(tmp_path), "hook_event_name": "PreToolUse",
        "tool_name": "Read", "tool_input": {"file_path": "/tmp/a.py"},
    }
    request = urllib.request.Request(
        f"http://127.0.0.1:{bridge.hook_server.port}/hook",
        data=json.dumps(event).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        body = json.loads(response.read())
    assert body["hookSpecificOutput"]["permissionDecision"] == "allow"
    assert bridge.audit.get_count() == 1

    await bridge.stop()


async def test_bridge_stop_shuts_down_hook_server(tmp_path):
    bridge = KaptnBridge(make_config(tmp_path))
    bridge._start_hook_server()
    assert bridge.hook_server.running
    await bridge.stop()
    assert not bridge.hook_server.running
