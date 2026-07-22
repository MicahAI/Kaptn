"""Tests for lifecycle helpers and the `kaptn stop` command."""

import json
import os
import subprocess
import sys
import time

import pytest
from click.testing import CliRunner

from bridge import lifecycle
from bridge.main import cli


class FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=b""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class TestLaunchdHelpers:
    def test_loaded_true(self, monkeypatch):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return FakeCompleted(returncode=0)

        monkeypatch.setattr(lifecycle.sys, "platform", "darwin")
        monkeypatch.setattr(subprocess, "run", fake_run)
        assert lifecycle.launchd_agent_loaded("com.test.label", uid=501) is True
        assert calls[0] == ["launchctl", "print", "gui/501/com.test.label"]

    def test_loaded_false(self, monkeypatch):
        monkeypatch.setattr(lifecycle.sys, "platform", "darwin")
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: FakeCompleted(returncode=113))
        assert lifecycle.launchd_agent_loaded("com.test.label", uid=501) is False

    def test_loaded_non_darwin(self, monkeypatch):
        monkeypatch.setattr(lifecycle.sys, "platform", "linux")
        assert lifecycle.launchd_agent_loaded("com.test.label") is False

    def test_bootout_success(self, monkeypatch):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return FakeCompleted(returncode=0)

        monkeypatch.setattr(lifecycle.sys, "platform", "darwin")
        monkeypatch.setattr(subprocess, "run", fake_run)
        assert lifecycle.bootout_launchd_agent("com.test.label", uid=501) is True
        assert calls[0] == ["launchctl", "bootout", "gui/501/com.test.label"]

    def test_bootout_failure(self, monkeypatch):
        monkeypatch.setattr(lifecycle.sys, "platform", "darwin")
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **k: FakeCompleted(returncode=3, stderr=b"no such service"),
        )
        assert lifecycle.bootout_launchd_agent("com.test.label", uid=501) is False

    def test_bootout_non_darwin(self, monkeypatch):
        monkeypatch.setattr(lifecycle.sys, "platform", "linux")
        assert lifecycle.bootout_launchd_agent("com.test.label") is False

    def test_default_uid_used(self, monkeypatch):
        seen = []
        monkeypatch.setattr(lifecycle.sys, "platform", "darwin")
        monkeypatch.setattr(
            subprocess, "run",
            lambda cmd, **k: seen.append(cmd) or FakeCompleted(returncode=0),
        )
        lifecycle.launchd_agent_loaded("com.test.label")
        assert f"gui/{os.getuid()}/com.test.label" in seen[0]


class TestFindProcesses:
    def test_collects_and_dedups_pids(self, monkeypatch):
        def fake_run(cmd, **kwargs):
            pattern = cmd[-1]
            if pattern == "kaptn start":
                return FakeCompleted(returncode=0, stdout="123\n456\n")
            if pattern == "kaptn claude serve":
                return FakeCompleted(returncode=0, stdout="456\n789\n")
            return FakeCompleted(returncode=1)

        monkeypatch.setattr(subprocess, "run", fake_run)
        assert lifecycle.find_kaptn_processes() == [123, 456, 789]

    def test_excludes_own_pid(self, monkeypatch):
        own = os.getpid()
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **k: FakeCompleted(returncode=0, stdout=f"{own}\n999\n"),
        )
        assert lifecycle.find_kaptn_processes() == [999]

    def test_ignores_garbage_output(self, monkeypatch):
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **k: FakeCompleted(returncode=0, stdout="12x\n42\n"),
        )
        assert lifecycle.find_kaptn_processes() == [42]

    def test_no_matches(self, monkeypatch):
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: FakeCompleted(returncode=1))
        assert lifecycle.find_kaptn_processes() == []


class TestTerminateProcesses:
    def _spawn(self, code):
        return subprocess.Popen([sys.executable, "-c", code])

    def test_graceful_termination(self):
        proc = self._spawn("import time; time.sleep(60)")
        stopped, killed = lifecycle.terminate_processes([proc.pid], grace_seconds=5)
        assert stopped == [proc.pid]
        assert killed == []
        assert not lifecycle._alive(proc.pid)

    def test_sigkill_escalation(self):
        proc = self._spawn(
            "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
            "print('ready', flush=True); time.sleep(60)"
        )
        time.sleep(0.5)  # let it install the SIGTERM handler
        stopped, killed = lifecycle.terminate_processes([proc.pid], grace_seconds=1)
        assert killed == [proc.pid]
        assert stopped == []
        proc.wait(timeout=5)

    def test_already_dead_pid(self):
        proc = self._spawn("pass")
        proc.wait(timeout=5)
        stopped, killed = lifecycle.terminate_processes([proc.pid], grace_seconds=1)
        assert stopped == [proc.pid]
        assert killed == []


class TestStopAll:
    def test_agent_and_processes(self, monkeypatch):
        monkeypatch.setattr(lifecycle, "launchd_agent_loaded", lambda label: True)
        monkeypatch.setattr(lifecycle, "bootout_launchd_agent", lambda label: True)
        monkeypatch.setattr(lifecycle, "find_kaptn_processes", lambda: [111])
        monkeypatch.setattr(
            lifecycle, "terminate_processes", lambda pids, grace_seconds: (pids, [])
        )
        monkeypatch.setattr(lifecycle.time, "sleep", lambda s: None)

        report = lifecycle.stop_all("com.test.label")
        assert report == {"agent_stopped": True, "stopped": [111], "killed": []}

    def test_nothing_running(self, monkeypatch):
        monkeypatch.setattr(lifecycle, "launchd_agent_loaded", lambda label: False)
        monkeypatch.setattr(lifecycle, "find_kaptn_processes", lambda: [])
        report = lifecycle.stop_all("com.test.label")
        assert report == {"agent_stopped": False, "stopped": [], "killed": []}


class TestStopCommand:
    @pytest.fixture
    def config_file(self, tmp_path):
        config = tmp_path / "kaptn.config.json"
        config.write_text(json.dumps({
            "claude": {"enabled": True, "launchd_label": "com.test.label"},
        }))
        return str(config)

    def test_stop_reports_agent_and_pids(self, monkeypatch, config_file):
        seen_labels = []

        def fake_stop_all(label):
            seen_labels.append(label)
            return {"agent_stopped": True, "stopped": [42], "killed": [43]}

        monkeypatch.setattr(lifecycle, "stop_all", fake_stop_all)
        result = CliRunner().invoke(cli, ["stop", "--config", config_file])
        assert result.exit_code == 0
        assert seen_labels == ["com.test.label"]
        assert "launchd agent 'com.test.label' stopped" in result.output
        assert "42" in result.output
        assert "Force-killed" in result.output and "43" in result.output

    def test_stop_nothing_running(self, monkeypatch, config_file):
        monkeypatch.setattr(
            lifecycle, "stop_all",
            lambda label: {"agent_stopped": False, "stopped": [], "killed": []},
        )
        result = CliRunner().invoke(cli, ["stop", "--config", config_file])
        assert result.exit_code == 0
        assert "Nothing was running" in result.output
