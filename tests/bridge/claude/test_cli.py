"""Tests for the `kaptn claude` CLI commands."""

import json

import pytest
from click.testing import CliRunner

from bridge.claude.cli import claude_group


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def config_file(tmp_path):
    config = tmp_path / "kaptn.config.json"
    config.write_text(json.dumps({
        "audit_db": ":memory:",
        "claude": {"enabled": True, "hook_port": 3002},
    }))
    return str(config)


class TestInstallCommand:
    def test_install_and_uninstall(self, runner, tmp_path, config_file):
        settings = tmp_path / "settings.json"

        result = runner.invoke(claude_group, [
            "install", "--config", config_file, "--settings", str(settings),
        ])
        assert result.exit_code == 0
        assert "installed" in result.output
        assert "3002" in result.output
        assert settings.exists()

        result = runner.invoke(claude_group, [
            "install", "--config", config_file, "--settings", str(settings),
        ])
        assert result.exit_code == 0
        assert "already installed" in result.output

        result = runner.invoke(claude_group, ["uninstall", "--settings", str(settings)])
        assert result.exit_code == 0
        assert "removed" in result.output

        result = runner.invoke(claude_group, ["uninstall", "--settings", str(settings)])
        assert result.exit_code == 0
        assert "No Kaptn hook" in result.output

    def test_install_port_override(self, runner, tmp_path, config_file):
        settings = tmp_path / "settings.json"
        result = runner.invoke(claude_group, [
            "install", "--config", config_file, "--settings", str(settings),
            "--port", "4111",
        ])
        assert result.exit_code == 0
        assert "4111" in result.output
        assert "--port 4111" in settings.read_text()

    def test_install_invalid_settings_fails(self, runner, tmp_path, config_file):
        settings = tmp_path / "settings.json"
        settings.write_text("{broken")
        result = runner.invoke(claude_group, [
            "install", "--config", config_file, "--settings", str(settings),
        ])
        assert result.exit_code == 1

    def test_uninstall_invalid_settings_fails(self, runner, tmp_path):
        settings = tmp_path / "settings.json"
        settings.write_text("{broken")
        result = runner.invoke(claude_group, ["uninstall", "--settings", str(settings)])
        assert result.exit_code == 1


class TestStatusCommand:
    def test_status_down(self, runner, config_file):
        result = runner.invoke(claude_group, [
            "status", "--config", config_file, "--port", "1",
        ])
        assert result.exit_code == 1
        assert "not reachable" in result.output

    def test_status_up(self, runner, config_file):
        from bridge.audit.audit_logger import AuditLogger
        from bridge.autopilot.auto_pilot_engine import AutoPilotEngine
        from bridge.autopilot.loop_detector import LoopDetector
        from bridge.autopilot.rule_evaluator import RuleEvaluator
        from bridge.claude.claude_adapter import ClaudeAdapter
        from bridge.claude.hook_server import ClaudeHookServer

        audit = AuditLogger(db_path=":memory:")
        autopilot = AutoPilotEngine(
            rule_evaluator=RuleEvaluator([]), loop_detector=LoopDetector()
        )
        server = ClaudeHookServer(ClaudeAdapter(autopilot, audit), port=0)
        server.start()
        try:
            result = runner.invoke(claude_group, [
                "status", "--config", config_file, "--port", str(server.port),
            ])
            assert result.exit_code == 0
            assert "healthy" in result.output
        finally:
            server.stop()
            audit.close()


class TestServeCommand:
    def test_serve_starts_and_stops(self, runner, tmp_path, monkeypatch):
        config = tmp_path / "kaptn.config.json"
        config.write_text(json.dumps({
            "audit_db": str(tmp_path / "audit.db"),
            "claude": {"enabled": True, "hook_port": 0},
        }))

        def interrupt(_seconds):
            raise KeyboardInterrupt

        monkeypatch.setattr("bridge.claude.cli.time.sleep", interrupt)
        result = runner.invoke(claude_group, ["serve", "--config", str(config)])
        assert result.exit_code == 0
        assert "listening" in result.output
