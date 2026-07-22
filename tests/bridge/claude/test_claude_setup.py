"""Tests for Claude Code settings hook install/uninstall."""

import json

import pytest

from bridge.claude.claude_setup import (
    HOOK_MARKER,
    build_hook_command,
    default_settings_path,
    install_hook,
    uninstall_hook,
)


@pytest.fixture
def settings_path(tmp_path):
    return tmp_path / ".claude" / "settings.json"


def read(settings_path):
    return json.loads(settings_path.read_text())


class TestInstall:
    def test_install_creates_settings(self, settings_path):
        assert install_hook(settings_path, port=3002) is True
        settings = read(settings_path)
        entries = settings["hooks"]["PreToolUse"]
        assert len(entries) == 1
        assert entries[0]["matcher"] == "*"
        command = entries[0]["hooks"][0]["command"]
        assert HOOK_MARKER in command
        assert "--port 3002" in command

    def test_install_idempotent(self, settings_path):
        install_hook(settings_path, port=3002)
        assert install_hook(settings_path, port=3002) is False  # no change
        assert len(read(settings_path)["hooks"]["PreToolUse"]) == 1

    def test_install_updates_port(self, settings_path):
        install_hook(settings_path, port=3002)
        assert install_hook(settings_path, port=4000) is True
        entries = read(settings_path)["hooks"]["PreToolUse"]
        assert len(entries) == 1
        assert "--port 4000" in entries[0]["hooks"][0]["command"]

    def test_install_preserves_other_hooks(self, settings_path):
        settings_path.parent.mkdir(parents=True)
        settings_path.write_text(json.dumps({
            "model": "opus",
            "hooks": {
                "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "other-tool"}]}],
                "Stop": [{"hooks": [{"type": "command", "command": "notify"}]}],
            },
        }))
        install_hook(settings_path, port=3002)
        settings = read(settings_path)
        assert settings["model"] == "opus"
        assert len(settings["hooks"]["PreToolUse"]) == 2
        assert settings["hooks"]["Stop"][0]["hooks"][0]["command"] == "notify"

    def test_install_rejects_invalid_json(self, settings_path):
        settings_path.parent.mkdir(parents=True)
        settings_path.write_text("{broken")
        with pytest.raises(ValueError):
            install_hook(settings_path, port=3002)

    def test_custom_python_interpreter(self, settings_path):
        install_hook(settings_path, port=3002, python="/opt/py/bin/python")
        command = read(settings_path)["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        assert command.startswith('"/opt/py/bin/python"')


class TestUninstall:
    def test_uninstall_removes_entry(self, settings_path):
        install_hook(settings_path, port=3002)
        assert uninstall_hook(settings_path) is True
        assert "hooks" not in read(settings_path)

    def test_uninstall_keeps_other_hooks(self, settings_path):
        settings_path.parent.mkdir(parents=True)
        settings_path.write_text(json.dumps({
            "hooks": {"PreToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": "other"}]}]},
        }))
        install_hook(settings_path, port=3002)
        assert uninstall_hook(settings_path) is True
        entries = read(settings_path)["hooks"]["PreToolUse"]
        assert len(entries) == 1
        assert entries[0]["hooks"][0]["command"] == "other"

    def test_uninstall_missing_file(self, settings_path):
        assert uninstall_hook(settings_path) is False

    def test_uninstall_no_kaptn_entry(self, settings_path):
        settings_path.parent.mkdir(parents=True)
        settings_path.write_text(json.dumps({"hooks": {}}))
        assert uninstall_hook(settings_path) is False


class TestHelpers:
    def test_default_settings_path_user(self):
        path = default_settings_path()
        assert path.name == "settings.json"
        assert path.parent.name == ".claude"
        assert str(path).startswith(str(path.home()))

    def test_default_settings_path_project(self):
        path = default_settings_path("/tmp/myproj")
        assert str(path) == "/tmp/myproj/.claude/settings.json"

    def test_build_hook_command_defaults_to_current_python(self):
        import sys
        command = build_hook_command(3002)
        assert sys.executable in command
        assert "-m bridge.claude.hook_client" in command
